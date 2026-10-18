"""PostgreSQL integration tests using an isolated, automatically removed schema.

Set DASHBOARD_TEST_DATABASE_URL to a disposable PostgreSQL database, then run:
PYTHONPATH=backend python -m unittest discover -s backend/test -p test_dashboard.py
"""

import asyncio
import os
import threading
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

# Allow route/service imports without loading real application credentials.
for key, value in {
    "DB_USER": "dashboard_test", "DB_PASS": "test", "DB_NAME": "dashboard_test",
    "GEMINI_API_KEY": "test", "SCHEDULE_ENABLE": "false",
}.items():
    os.environ.setdefault(key, value)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from database import get_db
from exceptions import DownloadException
from models import Base, FeedFetchLog, NewsArticle, RSSFeed
from routers.dashboard import router
from services.dashboard import get_dashboard_snapshot
from services.processing import extraction_eligible_condition
from services.scheduler_service import SchedulerService


@unittest.skipUnless(os.environ.get("DASHBOARD_TEST_DATABASE_URL"), "Set DASHBOARD_TEST_DATABASE_URL for PostgreSQL tests")
class DashboardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.base_engine = create_engine(os.environ["DASHBOARD_TEST_DATABASE_URL"])
        self.schema = "dashboard_test_" + uuid4().hex
        with self.base_engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = self.base_engine.execution_options(schema_translate_map={None: self.schema})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.db = self.sessions()
        self.settings = SimpleNamespace(ARTICLE_EXTRACTION_MAX_RETRY=3, SCHEDULE_ENABLE=False)
        self.scheduler = SchedulerService()
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.db.close()
        with self.base_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        self.base_engine.dispose()

    def feed(self, name="Example", **kwargs):
        feed = RSSFeed(name=name, url=["https://example.com/rss", "https://example.com/tech"], **kwargs)
        self.db.add(feed)
        self.db.flush()
        return feed

    def article(self, feed, content=None, retry=0, **kwargs):
        token = uuid4().hex
        article = NewsArticle(
            feed_id=feed.id if feed else None, title=token, link=f"https://example.com/{token}",
            content=content, retry_count=retry, **kwargs,
        )
        self.db.add(article)
        self.db.flush()
        return article

    def snapshot(self):
        return get_dashboard_snapshot(self.db, self.scheduler, self.settings)

    def test_empty_database_and_http_routes(self):
        snapshot = self.snapshot()
        self.assertEqual(snapshot.summary.total, 0)
        self.assertEqual(snapshot.summary.total_feeds, 0)
        self.assertEqual(snapshot.feeds, [])
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        with patch("routers.dashboard.settings", self.settings), patch("routers.dashboard.scheduler_service", self.scheduler):
            with TestClient(app) as client:
                response = client.get("/api/news/dashboard")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertIsNone(response.json()["live_processing_count"])
                for path, mime in [("/dashboard", "text/html"), ("/dashboard/app.js", "text/javascript"), ("/dashboard/style.css", "text/css")]:
                    response = client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(mime, response.headers["content-type"])
                self.assertEqual(client.post("/api/news/dashboard").status_code, 405)

    def test_counts_latest_log_ties_and_constant_query_count(self):
        regular = self.feed("<img src=x onerror=alert(1)>")
        disabled = self.feed("Disabled", skip_extraction=True)
        empty = self.feed("Empty", is_active=False)
        for content in [None, "", " \t\n\r", "None", " None "]:
            self.article(regular, content)
        self.article(regular, "Extracted text")
        self.article(regular, retry=3)
        invalid_link = self.article(regular)
        invalid_link.link = " \t"
        self.article(disabled, retry=8)  # Disabled takes precedence over exhausted.
        self.article(disabled, "Text")
        self.article(None)
        self.article(None, "Orphaned text")
        for status, stamp in [("error", self.now - timedelta(seconds=1)), ("success", self.now), ("partial", self.now)]:
            self.db.add(FeedFetchLog(
                feed_id=regular.id, status=status, fetch_timestamp=stamp,
                articles_found=20, articles_processed=18, execution_time_ms=100,
                error_message="<script>unsafe</script>" if status == "partial" else None,
            ))
        self.db.commit()
        queries = []

        def record(conn, cursor, statement, parameters, context, executemany):
            queries.append(statement)

        event.listen(self.engine, "before_cursor_execute", record)
        try:
            snapshot = self.snapshot()
        finally:
            event.remove(self.engine, "before_cursor_execute", record)
        self.assertEqual(len(queries), 4)
        self.assertEqual(snapshot.summary.model_dump(), {
            "total": 12, "with_content": 3, "missing_content": 9,
            "awaiting_extraction": 5, "extraction_disabled": 1,
            "retry_limit_reached": 1, "not_eligible": 2,
            "total_feeds": 3, "active_feeds": 2,
        })
        feeds = {feed.id: feed for feed in snapshot.feeds}
        self.assertEqual(feeds[regular.id].latest_fetch.status, "partial")
        self.assertEqual(feeds[regular.id].latest_fetch.valid_entries_submitted, 18)
        self.assertEqual(feeds[regular.id].articles.total, 8)
        self.assertEqual(feeds[empty.id].articles.total, 0)
        self.assertIsNone(feeds[empty.id].latest_fetch)
        self.assertEqual(feeds[regular.id].urls, regular.url)
        self.assertEqual(snapshot.summary.total - sum(f.articles.total for f in snapshot.feeds), 2)

    async def run_extraction(self, extract):
        with patch("services.scheduler_service.get_db", lambda: iter([self.sessions()])), patch(
            "services.scheduler_service.Extractor.extract", side_effect=extract,
        ), patch("services.scheduler_service.settings", self.settings):
            await self.scheduler._extract_content_job()
        self.db.expire_all()

    async def test_selection_persistence_retries_and_continue_after_exception(self):
        feed = self.feed()
        disabled = self.feed("Disabled", skip_extraction=True)
        inactive = self.feed("Inactive", is_active=False)
        success = self.article(feed, created_at=self.now - timedelta(seconds=3))
        empty = self.article(feed, " \t", retry=1, created_at=self.now - timedelta(seconds=2))
        download = self.article(feed, "None", created_at=self.now - timedelta(seconds=1))
        exception = self.article(feed, created_at=self.now)
        inactive_article = self.article(inactive)
        exhausted = self.article(feed, retry=3)
        skipped = self.article(disabled)
        ready = self.article(feed, "Already extracted")
        self.article(None)
        no_link = self.article(feed)
        no_link.link = ""
        ids = {a.id for a in [success, empty, download, exception, inactive_article]}
        self.db.commit()
        eligible = self.db.query(NewsArticle).join(RSSFeed).filter(extraction_eligible_condition(3)).all()
        self.assertEqual({a.id for a in eligible}, ids)
        called = []

        def extract(article):
            called.append(article.id)
            if article.id == exception.id:
                raise RuntimeError("Parser failed")
            if article.id == download.id:
                article.retry_count += 1  # Existing Extractor behavior.
                return None, None
            if article.id == empty.id:
                return " \t\n", None
            return "Saved content", "https://example.com/image.jpg"

        await self.run_extraction(extract)
        self.assertEqual(set(called), ids)
        self.assertLess(called.index(exception.id), called.index(success.id))
        self.assertEqual(success.content, "Saved content")
        self.assertEqual(success.image_url, "https://example.com/image.jpg")
        self.assertIsNotNone(success.updated_at)
        self.assertEqual(inactive_article.content, "Saved content")
        self.assertEqual(empty.retry_count, 2)
        self.assertEqual(download.retry_count, 1)
        self.assertEqual(exception.retry_count, 1)
        self.assertEqual(exhausted.retry_count, 3)
        self.assertEqual(skipped.retry_count, 0)
        self.assertEqual(ready.content, "Already extracted")
        for _ in range(3):
            await self.run_extraction(lambda article: (None, None))
        snapshot = self.snapshot()
        self.assertEqual(snapshot.summary.retry_limit_reached, 4)  # Three failures + previously exhausted.
        self.assertEqual(snapshot.summary.awaiting_extraction, 0)
        self.assertEqual(empty.retry_count, 3)
        self.assertEqual(download.retry_count, 3)
        self.assertEqual(exception.retry_count, 3)

    async def test_real_extractor_with_mocked_download_and_parser(self):
        feed = self.feed()
        article = self.article(feed, retry=2)
        article_id = article.id
        self.db.commit()
        with patch("services.scheduler_service.get_db", lambda: iter([self.sessions()])), patch(
            "services.extractors.Extractor.download_page", side_effect=DownloadException(article.link),
        ), patch("services.scheduler_service.settings", self.settings):
            await self.scheduler._extract_content_job()
        self.db.expire_all()
        self.assertEqual(self.db.get(NewsArticle, article_id).retry_count, 3)
        article.retry_count = 0
        self.db.commit()
        with patch("services.scheduler_service.get_db", lambda: iter([self.sessions()])), patch(
            "services.extractors.Extractor.download_page", return_value='<html><meta property="og:image" content="https://example.com/picture.jpg"></html>',
        ), patch("services.extractors.extract", return_value="Parsed article content"), patch(
            "services.scheduler_service.settings", self.settings,
        ):
            await self.scheduler._extract_content_job()
        self.db.expire_all()
        self.assertEqual(article.content, "Parsed article content")
        self.assertEqual(article.image_url, "https://example.com/picture.jpg")

    async def test_newest_first_batch_limit(self):
        feed = self.feed()
        articles = [self.article(feed, created_at=self.now + timedelta(seconds=i)) for i in range(35)]
        expected = [a.id for a in reversed(articles[5:])]
        self.db.commit()
        called = []

        def extract(article):
            called.append(article.id)
            return "Content", None

        await self.run_extraction(extract)
        self.assertEqual(called, expected)
        self.assertEqual(self.snapshot().summary.awaiting_extraction, 5)

    async def test_download_does_not_block_event_loop(self):
        self.article(self.feed())
        self.db.commit()
        heartbeat = threading.Event()
        responsive = []

        def extract(article):
            responsive.append(heartbeat.wait(timeout=1))
            return "Content", None

        async def pulse():
            await asyncio.sleep(0.02)
            heartbeat.set()

        await asyncio.gather(self.run_extraction(extract), pulse())
        self.assertEqual(responsive, [True])

    async def test_scheduler_running_status_and_next_runs(self):
        self.scheduler.start()
        try:
            snapshot = self.snapshot()
            self.assertTrue(snapshot.scheduler.scheduler_running)
            self.assertFalse(snapshot.scheduler.enabled)
            self.assertEqual({job.id for job in snapshot.scheduler.jobs}, {"fetch_all_feeds", "extract_content"})
            self.assertTrue(all(job.next_run_time is not None for job in snapshot.scheduler.jobs))
        finally:
            self.scheduler.stop()


if __name__ == "__main__":
    unittest.main()
