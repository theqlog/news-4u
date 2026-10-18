"""Run: PYTHONPATH=backend python -m unittest discover -s backend/test -p test_rss_multi_url.py"""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from pydantic import ValidationError
from schemas import RSSFeedCreate
from services.rss import RSSService


class FeedSchemaTests(unittest.TestCase):
    def test_urls_are_required_and_validated(self):
        for urls in ([], 'https://example.com/rss', ['invalid'], [None]):
            with self.assertRaises(ValidationError):
                RSSFeedCreate(name='Example', url=urls)
        feed = RSSFeedCreate(name='Example', url=['https://example.com/rss'] * 2)
        self.assertEqual(feed.url, ['https://example.com/rss'])


class CrawlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_multi_url_deduplication_and_partial_failure(self):
        db = MagicMock()
        service = RSSService(db)
        xml = '<rss version="2.0"><channel><title>Test</title><item><title>News</title><link>https://example.com/story</link></item></channel></rss>'
        service._fetch_with_retry = AsyncMock(side_effect=[SimpleNamespace(text=xml), RuntimeError('offline'), SimpleNamespace(text=xml)])
        service._process_articles = AsyncMock(side_effect=lambda entries, feed: len(entries))
        feed = SimpleNamespace(id=1, name='Example', url=['https://a.com/rss', 'https://b.com/rss', 'https://c.com/rss'], category='News')
        result = await service.fetch_feed_async(feed)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['articles_found'], 2)
        self.assertEqual(result['articles_processed'], 1)
        self.assertEqual(service._fetch_with_retry.await_count, 3)
        log = db.add.call_args.args[0]
        self.assertEqual(log.status, 'partial')
        self.assertIsInstance(log.execution_time_ms, int)
        article = service._build_article_object({'title': 'News', 'link': 'https://example.com/story'}, feed)
        self.assertEqual(article['category'], 'News')
        self.assertEqual(article['feed_id'], 1)

    async def test_all_urls_fail(self):
        service = RSSService()
        service._fetch_with_retry = AsyncMock(side_effect=RuntimeError('offline'))
        result = await service.fetch_feed_async(SimpleNamespace(id=1, name='Example', url=['https://a.com/rss']))
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['articles_processed'], 0)
