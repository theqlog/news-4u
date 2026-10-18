"""
Pydantic schemas for API request/response models.
"""

from pydantic import BaseModel, HttpUrl, Field, AfterValidator
from typing import Optional, List, Annotated
from datetime import datetime


def validate_feed_urls(urls: List[str]) -> List[str]:
    for url in urls:
        HttpUrl(url)
    return list(dict.fromkeys(urls))


FeedURLs = Annotated[List[str], Field(min_length=1), AfterValidator(validate_feed_urls)]


class RSSFeedBase(BaseModel):
    name: str
    url: FeedURLs
    category: Optional[str] = None


class RSSFeedCreate(RSSFeedBase):
    pass


class RSSFeedUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[FeedURLs] = None
    category: Optional[str] = None
    is_active: Optional[bool] = None
    skip_extraction: Optional[bool] = None


class RSSFeedResponse(RSSFeedBase):
    id: int
    is_active: bool
    skip_extraction: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class NewsArticleBase(BaseModel):
    title: str
    summary: Optional[str] = None
    content: Optional[str] = None
    link: str
    author: Optional[str] = None
    published_date: Optional[datetime] = None
    category: Optional[str] = None
    feed_id: Optional[int] = None
    image_url: Optional[str] = None
    slug: Optional[str] = None


class NewsArticleCreate(NewsArticleBase):
    pass


class NewsArticleResponse(NewsArticleBase):
    id: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    feed_name: Optional[str] = None

    class Config:
        from_attributes = True


class NewsArticleList(BaseModel):
    articles: List[NewsArticleResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


class FeedFetchLogResponse(BaseModel):
    id: int
    feed_id: int
    fetch_timestamp: datetime
    status: str
    articles_found: int
    articles_processed: int
    error_message: Optional[str] = None
    execution_time_ms: Optional[int] = None

    class Config:
        from_attributes = True


class HealthCheckResponse(BaseModel):
    status: str
    timestamp: datetime
    database_connected: bool
    feeds_count: int
    articles_count: int

class FeedFetchStatus(str):
    STARTING = "starting"
    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"