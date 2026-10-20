"""
Scheduler service for managing cronjobs.
"""

import asyncio
import logging
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from database import get_db
from services.rss import RSSService
from services.extractors import Extractor
from models import NewsArticle, RSSFeed
from services.processing import extraction_eligible_condition, has_content
from config.settings import settings

logger = logging.getLogger(__name__)


class SchedulerService:
    """Service for managing scheduled tasks."""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.is_running = False
    
    def start(self):
        print("---- Starting Scheduler Service ----")
        """Start the scheduler."""
        if not self.is_running:
            # A stopped APScheduler executor cannot be reused. A fresh instance
            # also isolates an immediately preceding asynchronous shutdown.
            self.scheduler = AsyncIOScheduler()
            self.scheduler.start()
            self.is_running = True
            logger.info("Scheduler started")
            # Add the cronjobs
            self._add_feed_fetching_job()
            self._add_content_extraction_job()
    
    def stop(self):
        """Stop the scheduler."""
        if self.is_running:
            self.scheduler.shutdown()
            self.is_running = False
            logger.info("Scheduler stopped")
    
    def _add_feed_fetching_job(self):
        """Add the job to fetch all feeds every 15 minutes."""
        self.scheduler.add_job(
            func=self._fetch_all_feeds_job,
            trigger=CronTrigger(minute="*/15"),  # Every 15 minutes
            id="fetch_all_feeds",
            name="Fetch all RSS feeds",
            replace_existing=True,
            max_instances=1
        )
        logger.info("Added feed fetching job (every 15 minutes)")
    
    def _add_content_extraction_job(self):
        """Add the job to extract content every minute."""
        self.scheduler.add_job(
            func=self._extract_content_job,
            trigger=CronTrigger(minute="*"),  # Every minute
            id="extract_content",
            name="Extract article content",
            replace_existing=True,
            max_instances=1
        )
        logger.info("Added content extraction job (every minute)")
    
    async def _fetch_all_feeds_job(self):
        """Job to fetch all RSS feeds."""
        logger.info("---- Starting scheduled feed fetching job ----")
        try:
            db = next(get_db())
            service = RSSService(db)
            result = await service.fetch_all_feeds()
            logger.info(f"Feed fetching completed: {result}")
        except Exception as e:
            logger.error(f"Error in feed fetching job: {e}")
        finally:
            if 'db' in locals():
                db.close()
    
    async def _extract_content_job(self):
        """Job to extract content for articles that haven't been extracted."""
        logger.info("---- Starting scheduled content extraction job ----")
        try:
            db = next(get_db())

            articles_without_content = (
                db.query(NewsArticle)
                .join(RSSFeed, NewsArticle.feed_id == RSSFeed.id)
                .filter(extraction_eligible_condition(settings.ARTICLE_EXTRACTION_MAX_RETRY))
                .order_by(NewsArticle.created_at.desc(), NewsArticle.id.desc())
                .limit(30)
                .all()
            )

            if not articles_without_content:
                logger.info("No articles found that need content extraction")
                return
            
            logger.info(f"Found {len(articles_without_content)} articles that need content extraction")

            extractor = Extractor()
            extracted_count = 0

            for article in articles_without_content:
                retry_before = article.retry_count or 0
                succeeded = False
                try:
                    logger.info(f"Extracting content for article {article.id}: {article.title}")
                    # Downloads/parsing are synchronous; keep the API responsive
                    # while waiting, with database work staying on this thread.
                    content, extracted_image_url = await asyncio.to_thread(extractor.extract, article)
                    if has_content(content):
                        article.content = content
                        succeeded = True
                        extracted_count += 1
                    if extracted_image_url and not article.image_url:
                        article.image_url = extracted_image_url
                except Exception:
                    logger.exception("Scheduler: Error extracting content for article %s", article.id)
                finally:
                    # Extractor may already increment retries for a download failure.
                    # Assign from the pre-attempt value to count every failure once.
                    if not succeeded:
                        article.retry_count = retry_before + 1
                    article.updated_at = datetime.now(timezone.utc)

                # Keep completed attempts if a later article fails or the job stops.
                db.commit()

            logger.info(f"Content extraction job completed. Extracted content for {extracted_count} articles")
            
        except Exception as e:
            if 'db' in locals():
                db.rollback()
            logger.error(f"Error in content extraction job: {e}")
        finally:
            if 'db' in locals():
                db.close()
    
    def get_job_status(self) -> dict:
        """Get the status of all scheduled jobs."""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger)
            })
        
        return {
            "scheduler_running": self.is_running,
            "jobs": jobs
        }


# Global scheduler instance
scheduler_service = SchedulerService()
