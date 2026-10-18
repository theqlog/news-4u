"""
RSS service for fetching and processing RSS feeds.
"""

import asyncio
from datetime import timezone
from datetime import datetime
import logging
import re
import time
import traceback
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from schemas import FeedFetchStatus, NewsArticleCreate
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

from config.rss_feeds import RSSFeed
import feedparser
import httpx
from lib.utils import get_or_build_slug
from models import FeedFetchLog, NewsArticle, RSSFeed as RSSFeedModel
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert


logger = logging.getLogger(__name__)



class RSSService:
    """Service for handling RSS feed operations."""
    def __init__(self, db: Optional[Session] = None):
        self.db = db
        self.timeout = 30  # seconds
        self.batch_size = 100  
        self._slug_cache = set()  
        self._cache_timestamp = None
        self._cache_ttl = 300  # 5 minutes cache TTL
        
        # HTTP client headers to avoid 403 errors
        self._headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,vi;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
    
    # ============================================================================
    # PUBLIC METHODS
    # ============================================================================
    
    async def fetch_feed_async(self, feed: RSSFeedModel) -> Dict:
        logger.info(f'Starting fetch for feed: {feed.name} ----')
        start_time = time.time()
        log_entry = FeedFetchLog(
            feed_id=feed.id,
            status=FeedFetchStatus.STARTING,            
            articles_found=0,
            articles_processed=0
        )
        logger.debug(f"Created log entry for feed {feed.name} with status 'starting'")
        if self.db is not None:
            logger.debug(f"Adding log entry to database for feed {feed.name}")
            self.db.add(log_entry)
            self.db.commit()


        articles_found = 0
        articles_processed = 0
        errors = []
        successful_urls = 0
        seen_links = set()
        for feed_url in dict.fromkeys(feed.url):
            try:
                response = await self._fetch_with_retry(feed_url)
                loop = asyncio.get_running_loop()
                parsed_feed = await loop.run_in_executor(None, feedparser.parse, response.text)
                if parsed_feed.bozo and not parsed_feed.entries:
                    raise ValueError(f"Invalid RSS feed: {parsed_feed.get('bozo_exception', 'parse error')}")
                articles_found += len(parsed_feed.entries)
                entries = []
                for entry in parsed_feed.entries:
                    link = self._safe_get_string(entry, 'link')
                    if link and link in seen_links:
                        continue
                    entries.append(entry)
                articles_processed += await self._process_articles(entries, feed)
                seen_links.update(self._safe_get_string(entry, "link") for entry in entries)
                successful_urls += 1
            except Exception as exc:
                logger.exception("Error fetching %s for %s", feed_url, feed.name)
                if self.db is not None:
                    self.db.rollback()
                errors.append(f"{feed_url}: {exc}")

        status = FeedFetchStatus.SUCCESS
        if errors:
            status = FeedFetchStatus.PARTIAL if successful_urls else FeedFetchStatus.ERROR
        execution_time = int((time.time() - start_time) * 1000)
        log_entry.status = status
        log_entry.articles_found = articles_found
        log_entry.articles_processed = articles_processed
        log_entry.execution_time_ms = execution_time
        log_entry.error_message = "; ".join(errors) if errors else None
        if self.db is not None:
            self.db.commit()
        result = {
            "status": status,
            "articles_found": articles_found,
            "articles_processed": articles_processed,
            "execution_time": execution_time,
        }
        if errors:
            result["error"] = "; ".join(errors)
        return result

    async def fetch_all_feeds(self) -> Dict:
        """Fetch all active feeds in parallel."""
        if self.db is None:
            return {"status": "error", "message": "No database connection"}

        feeds = self.db.query(RSSFeedModel).filter(RSSFeedModel.is_active == True).all()

        if not feeds:
            return {
                "status": FeedFetchStatus.SUCCESS,
                "message": "No active feeds to fetch",
                "feeds_processed": 0,
                "total_articles_found": 0,
                "total_articles_processed": 0
            }

        # Create tasks for parallel execution
        tasks = [self.fetch_feed_async(feed) for feed in feeds]

        # Execute all feeds in parallel with exception handling
        results_raw = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        results = []
        total_articles_found = 0
        total_articles_processed = 0

        for feed, result in zip(feeds, results_raw):
            if isinstance(result, Exception):
                logger.error(f"Error processing feed {feed.name}: {result}")
                results.append({
                    "feed_name": feed.name,
                    "status": FeedFetchStatus.ERROR,
                    "error": str(result)
                })
            else:
                results.append({
                    "feed_name": feed.name,
                    **result
                })

                if result.get("status") in (FeedFetchStatus.SUCCESS, FeedFetchStatus.PARTIAL):
                    total_articles_found += result.get("articles_found", 0)
                    total_articles_processed += result.get("articles_processed", 0)

        statuses = [result["status"] for result in results]
        overall_status = FeedFetchStatus.SUCCESS
        if any(status != FeedFetchStatus.SUCCESS for status in statuses):
            overall_status = (
                FeedFetchStatus.ERROR if all(status == FeedFetchStatus.ERROR for status in statuses)
                else FeedFetchStatus.PARTIAL
            )
        return {
            "status": overall_status,
            "feeds_processed": len(feeds),
            "total_articles_found": total_articles_found,
            "total_articles_processed": total_articles_processed,
            "results": results
        }
    
    
    async def cleanup_all_data(self):
        """
        Clean up all data from the database.
        """
        if self.db is not None:
            self.db.query(NewsArticle).delete()
            self.db.query(FeedFetchLog).delete()
            self.db.commit()

    async def cleanup_feed_data(self, feed_name: str):
        """
        Clean up data for a specific feed.
        """
        if self.db is not None:
            self.db.query(NewsArticle).filter(NewsArticle.source_name == feed_name).delete()
            self.db.query(FeedFetchLog).filter(FeedFetchLog.feed_name == feed_name).delete()
            self.db.commit()
    
    async def delete_article_content(self, article_id: int):
        """
        Delete content for a specific article.
        """
        if self.db is not None:
            self.db.query(NewsArticle).filter(NewsArticle.id == article_id).update({
                NewsArticle.content: None,
                NewsArticle.image_url: None
            })
            self.db.commit()

    
    def get_recent_articles(self, limit: int = 50) -> List[NewsArticle]:
        """
        Get recent articles across all categories.
        """
        if self.db is None:
            return []
        return self.db.query(NewsArticle).order_by(
            NewsArticle.published_date.desc()
        ).limit(limit).all()
    
    def get_articles_by_source(self, source_name: str, limit: int = 50) -> List[NewsArticle]:
        """
        Get articles by source name.
        """
        if self.db is None:
            return []
        return self.db.query(NewsArticle).filter(
            NewsArticle.source_name == source_name
        ).order_by(
            NewsArticle.published_date.desc()
        ).limit(limit).all()
    
    def get_feed_by_name_from_db(self, name: str) -> RSSFeedModel | None:
        """
        Get a specific RSS feed from database by name.
        """
        if self.db is None:
            return None
        return self.db.query(RSSFeedModel).filter(RSSFeedModel.name == name).first()
    
    def toggle_feed_status(self, feed_name: str) -> Dict:
        """
        Toggle the active status of a feed.
        """
        if self.db is None:
            return {"status": "error", "message": "No database connection"}
        
        feed = self.get_feed_by_name_from_db(feed_name)
        if not feed:
            return {"status": "error", "message": f"Feed '{feed_name}' not found"}
        
        feed.is_active = not feed.is_active
        self.db.commit()
        
        return {
            "status": "success",
            "feed_name": feed.name,
            "is_active": feed.is_active,
            "message": f"Feed '{feed_name}' {'activated' if feed.is_active else 'deactivated'}"
        }
    
    
    def delete_feed(self, feed_name: str) -> Dict:
        """
        Delete a feed from the database.
        """
        if self.db is None:
            return {"status": "error", "message": "No database connection"}
        
        feed = self.get_feed_by_name_from_db(feed_name)
        if not feed:
            return {"status": "error", "message": f"Feed '{feed_name}' not found"}
        
        self.db.delete(feed)
        self.db.commit()
        return {"status": "success", "message": f"Feed '{feed_name}' deleted successfully"}
    
    # ============================================================================
    # PRIVATE METHODS
    # ============================================================================
    
    async def _fetch_with_retry(self, url: str, max_retries: int = 3) -> httpx.Response:
        """
        Fetch URL with retry logic and proper headers to avoid 403 errors.
        """
        for attempt in range(max_retries):
            try:
                logger.debug(f"Fetching URL: {url}, attempt {attempt + 1}")
                async with httpx.AsyncClient(
                    timeout=self.timeout, 
                    follow_redirects=True,
                    headers=self._headers
                ) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    return response
                    
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403 and attempt < max_retries - 1:
                    logger.warning(f"403 Forbidden on attempt {attempt + 1} for {url}, retrying...")
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    raise e
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Request failed on attempt {attempt + 1} for {url}: {e}, retrying...")
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    raise e
        
        raise Exception(f"Failed to fetch {url} and all fallbacks after {max_retries} attempts each")
    
    async def _process_articles(self, entries: List, feed: RSSFeedModel) -> int:
        """
        Process RSS feed entries into news articles (metadata only, no content extraction).
        """
        if not entries:
            return 0
        
        articles_to_add = []
        logger.info(f'---- Processing {len(entries)} articles from {feed.name} ----')
                
        for entry in entries:
            try:
                data = self._build_article_object(entry, feed)
                articles_to_add.append(data)
            except Exception as e:
                logger.warning(f"Skipping invalid article: {e}")
                continue

        if articles_to_add:
            stmt = pg_insert(NewsArticle).values(articles_to_add)
            stmt = stmt.on_conflict_do_nothing(index_elements=['link'])
            
            self.db.execute(stmt)
            self.db.commit()
        
        return len(articles_to_add)

    def _build_article_object(self, entry: Dict[str, Any], feed: RSSFeedModel) -> Optional[NewsArticle]:
        title = self._safe_get_string(entry, 'title')
        link = self._safe_get_string(entry, 'link')
        if not link or not title:
            raise ValueError(f'[Feed {feed.name}] Skipping article due to missing title or link. Title: "{title}", Link: "{link}"')

        raw_data = {
            "title": title,
            "summary": self._extract_summary(entry),
            "link": link,
            "author": self._safe_get_string(entry, 'author'),
            "published_date": self._extract_published_date(entry),
            "category": feed.category,
            "image_url": self._extract_image(entry),
            "slug": get_or_build_slug(link, title),
            "feed_id": feed.id,
        }

        validated_article = NewsArticleCreate(**raw_data)

        return validated_article.model_dump()

    def _extract_summary(self, entry) -> Optional[str]:
        """
        Extract summary from RSS entry, cleanup html tags if exists.
        """
        summary = self._safe_get_string(entry, 'summary') or self._safe_get_string(entry, 'description')
        
        if summary:
            soup = BeautifulSoup(summary, 'html.parser')
            return soup.get_text().strip()
        
        return None
    
    def _extract_published_date(self, entry) -> Optional[datetime]:
        """
        Robustly extract published date from RSS entry, trying all common fields.
        Always returns a UTC datetime (with tzinfo=timezone.utc).
        """
        
        
        date_fields = [
            'published', 'pubDate', 'updated', 'created', 'date',
            'dc:date', 'dc:created', 'dc:issued', 'dc:modified', 'issued', 'modified'
        ]
        
        for field in date_fields:
            date_str = entry.get(field, '')
            if date_str:
                # Normalize timezone format: GMT+7 -> +07, GMT-5 -> -05
                date_str = re.sub(r'GMT\+(\d{1,2})', r'+\1', date_str)
                date_str = re.sub(r'GMT-(\d{1,2})', r'-\1', date_str)
                
                try:
                    parsed_date = dateutil_parser.parse(date_str)
                    
                    # Ensure it has timezone info, default to UTC if not
                    if parsed_date.tzinfo is None:
                        parsed_date = parsed_date.replace(tzinfo=timezone.utc)
                    else:
                        # Convert to UTC
                        parsed_date = parsed_date.astimezone(timezone.utc)
                    
                    return parsed_date
                except (ValueError, TypeError) as e:
                    logger.debug(f"Failed to parse date from field '{field}': {date_str}, error: {e}")
                    continue
        
        # If no date found, return None
        return None
    
    def _extract_image(self, entry) -> Optional[str]:
        """
        Extract image URL from RSS entry.
        """
        image_fields = ['media_content', 'media:thumbnail', 'enclosure', 'image']
        
        for field in image_fields:
            if field in entry:
                media_content = entry[field]
                
                # Handle different media content formats
                if isinstance(media_content, list) and len(media_content) > 0:
                    # Take the first media item
                    media_item = media_content[0]
                    if isinstance(media_item, dict):
                        url = media_item.get('url') or media_item.get('href')
                        if url:
                            return url
                elif isinstance(media_content, dict):
                    # Single media item
                    url = media_content.get('url') or media_content.get('href')
                    if url:
                        return url
                elif isinstance(media_content, str):
                    # Direct URL string
                    return media_content
        
        # Try to extract from content/summary if no media found
        content_fields = ['summary', 'description', 'content']
        for field in content_fields:
            content = self._safe_get_string(entry, field)
            if content:
                # Look for img tags
                soup = BeautifulSoup(content, 'html.parser')
                img_tag = soup.find('img')
                if img_tag and img_tag.get('src'):
                    return img_tag.get('src')
        
        return None
    
    def _make_absolute_url(self, url: str, base_url: str) -> str:
        """
        Convert relative URL to absolute URL.
        """
        return urljoin(base_url, url)
    
    def _is_valid_content_image(self, image_url: str) -> bool:
        """
        Check if image URL is valid for content.
        """
        if not image_url:
            return False
        
        # Skip data URLs
        if image_url.startswith('data:'):
            return False
        
        # Skip very small images (likely icons)
        if any(size in image_url.lower() for size in ['16x16', '32x32', '48x48']):
            return False
        
        # Skip tracking pixels
        if any(tracker in image_url.lower() for tracker in ['tracking', 'pixel', 'beacon']):
            return False
        
        return True
    
    def _clean_extracted_content(self, text: str) -> str:
        """
        Clean and format extracted content.
        """
        if not text:
            return ""
        
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove HTML comments
        text = re.sub(r'<!--.*?-->', '', text, flags=re.DOTALL)
        
        # Clean up line breaks
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        
        # Remove multiple consecutive line breaks
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # Strip leading/trailing whitespace
        text = text.strip()
        
        return text
    
    def _sanitize_html_attributes(self, html_content: str) -> str:
        """
        Remove unwanted HTML attributes while preserving content structure.
        """
        if not html_content:
            return ""
        
        # Parse the HTML content
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Define attributes to remove
        attributes_to_remove = [
            'class', 'id', 'style', 'data-*', 'onclick', 'onload', 'onerror',
            'onmouseover', 'onmouseout', 'onfocus', 'onblur', 'onchange',
            'oninput', 'onsubmit', 'onreset', 'onselect', 'onunload',
            'onkeydown', 'onkeyup', 'onkeypress', 'onmousedown', 'onmouseup',
            'onmousemove', 'onmouseenter', 'onmouseleave', 'oncontextmenu',
            'onabort', 'onbeforeunload', 'onerror', 'onhashchange', 'onmessage',
            'onoffline', 'ononline', 'onpagehide', 'onpageshow', 'onpopstate',
            'onresize', 'onstorage', 'onbeforeprint', 'onafterprint',
            'aria-*', 'role', 'tabindex', 'accesskey', 'contenteditable',
            'draggable', 'dropzone', 'spellcheck', 'translate'
        ]
        
        # Process all tags
        for tag in soup.find_all():
            if tag.name:  # Ensure it's a tag
                # Remove specified attributes
                for attr in list(tag.attrs.keys()):
                    # Remove data-* attributes
                    if attr.startswith('data-'):
                        del tag[attr]
                    # Remove aria-* attributes
                    elif attr.startswith('aria-'):
                        del tag[attr]
                    # Remove other specified attributes
                    elif attr in attributes_to_remove:
                        del tag[attr]
                
                # Special handling for img tags - preserve essential attributes
                if tag.name == 'img':
                    # Keep only essential img attributes
                    essential_img_attrs = ['src', 'alt', 'title', 'width', 'height']
                    for attr in list(tag.attrs.keys()):
                        if attr not in essential_img_attrs:
                            del tag[attr]
                
                # Special handling for a tags - preserve href
                elif tag.name == 'a':
                    # Keep only href attribute
                    for attr in list(tag.attrs.keys()):
                        if attr != 'href':
                            del tag[attr]
                
                # Special handling for table tags - preserve basic table structure
                elif tag.name in ['table', 'tr', 'td', 'th']:
                    # Keep only essential table attributes
                    essential_table_attrs = ['colspan', 'rowspan']
                    for attr in list(tag.attrs.keys()):
                        if attr not in essential_table_attrs:
                            del tag[attr]
        
        return str(soup)
    

    def _extract_main_image_url_from_html(self, html: str, base_url: str) -> Optional[str]:
        """
        Extract the main image URL from HTML content.
        """
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Look for Open Graph image
            og_image = soup.find('meta', property='og:image')
            if og_image and og_image.get('content'):
                return self._make_absolute_url(og_image.get('content'), base_url)
            
            # Look for Twitter image
            twitter_image = soup.find('meta', attrs={'name': 'twitter:image'})
            if twitter_image and twitter_image.get('content'):
                return self._make_absolute_url(twitter_image.get('content'), base_url)
            
            # Look for the first large image in the content
            images = soup.find_all('img')
            for img in images:
                src = img.get('src', '')
                if src and self._is_valid_content_image(src):
                    # Check if it's a large image (likely main content image)
                    width = img.get('width', '0')
                    height = img.get('height', '0')
                    
                    try:
                        width_int = int(width) if width.isdigit() else 0
                        height_int = int(height) if height.isdigit() else 0
                        
                        # Consider it a main image if it's reasonably large
                        if width_int > 300 or height_int > 200:
                            return self._make_absolute_url(src, base_url)
                    except (ValueError, AttributeError):
                        # If we can't parse dimensions, check if it's a reasonable URL
                        if len(src) > 20:  # Likely a real image URL
                            return self._make_absolute_url(src, base_url)
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting main image from HTML: {e}")
            return None

    def _safe_get_string(self, entry, key: str, default: str = "") -> str:
        """
        Safely extract a string value from an entry, handling potential list/dict issues.
        """
        value = entry.get(key, default)
        if isinstance(value, (list, tuple)):
            return default if not value else str(value[0])
        return str(value) if value is not None else default