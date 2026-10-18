"""
Database models for RSS feeds and news articles.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Index
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime

Base = declarative_base()


class RSSFeed(Base):
    __tablename__ = "rss_feeds"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    url = Column(ARRAY(Text), nullable=False)
    category = Column(String(50), nullable=True)
    is_active = Column(Boolean, default=True)
    skip_extraction = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    articles = relationship("NewsArticle", back_populates="feed")

    __table_args__ = (
        Index('ix_rss_feeds_is_active', 'is_active'),
    )


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    summary = Column(Text)
    content = Column(Text)
    link = Column(String(1000), nullable=False, unique=True)
    author = Column(String(255))
    published_date = Column(DateTime(timezone=True))
    category = Column(String(50), nullable=True)
    image_url = Column(String(1000))
    slug = Column(String(1000), unique=True)
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    feed_id = Column(ForeignKey("rss_feeds.id"), index=True)

    feed = relationship("RSSFeed", back_populates="articles", lazy="joined")

    # Add indexes for common query patterns
    __table_args__ = (
        Index('ix_news_articles_published_date', 'published_date'),
        Index('ix_news_articles_category', 'category'),
        Index('ix_news_articles_feed_id_created_at', 'feed_id', 'created_at'),
    )


class FeedFetchLog(Base):
    __tablename__ = "feed_fetch_logs"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    feed_id = Column(ForeignKey("rss_feeds.id"), index=True)

    fetch_timestamp = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String(50), nullable=False)  # success, error, partial
    articles_found = Column(Integer, default=0)
    articles_processed = Column(Integer, default=0)
    error_message = Column(Text)
    execution_time_ms = Column(Integer)
