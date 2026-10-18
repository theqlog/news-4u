"""
RSS Feeds Configuration
"""

from typing import List, Optional
from dataclasses import dataclass

@dataclass
class RSSFeed:
    name: str
    url: List[str]
    category: Optional[str] = None
    is_active: bool = True

# RSS Feeds Configuration - SEED DATA ONLY
# This dictionary is used by scripts/init_db.py to populate the database with initial feeds.
# After seeding, the database becomes the source of truth. Changes here won't affect runtime.
# Each source groups one or more RSS URLs under one name and category.
RSS_FEEDS: List[RSSFeed] = [
    RSSFeed(name="Vnexpress", url=["https://vnexpress.net/rss/the-gioi.rss"], is_active=True),
    RSSFeed(name="Tuoitre", url=["https://tuoitre.vn/home.rss", "https://tuoitre.vn/the-gioi.rss", "https://tuoitre.vn/thoi-su.rss", "https://tuoitre.vn/suc-khoe.rss"], is_active=True),
    RSSFeed(name="TechCrunch", url=["https://techcrunch.com/feed/"], is_active=True),
    RSSFeed(name="The Verge", url=["https://www.theverge.com/rss/index.xml"], is_active=True),
    RSSFeed(name="Engadget", url=["https://www.engadget.com/rss.xml"], is_active=True),
    RSSFeed(name="CNBC", url=["https://www.cnbc.com/id/100003114/device/rss/rss.html"], is_active=True),
    RSSFeed(name="NBC News", url=["https://feeds.nbcnews.com/nbcnews/public/news"], is_active=True),
    RSSFeed(name="ABC News", url=["https://abcnews.go.com/abcnews/usheadlines"], is_active=True),
    RSSFeed(name="BBC News", url=["https://feeds.bbci.co.uk/news/rss.xml"], is_active=True),
    RSSFeed(name="CNBC Global", url=["https://www.cnbc.com/id/100727362/device/rss/rss.html"], is_active=True),
    RSSFeed(name="CBSNews", url=["https://www.cbsnews.com/latest/rss/world"], is_active=True),
]
