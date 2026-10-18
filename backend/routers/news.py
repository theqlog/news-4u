"""
News API routes for fetching articles and managing RSS feeds.
"""
from datetime import datetime, timedelta
import logging
from typing import List, Optional

from database import get_db
from fastapi import APIRouter, Depends, HTTPException, Query
from models import FeedFetchLog, NewsArticle, RSSFeed
from schemas import (
    FeedFetchLogResponse,
    HealthCheckResponse,
    NewsArticleList,
    NewsArticleResponse,
    RSSFeedResponse,
    RSSFeedUpdate,
)
from schemas import RSSFeedCreate
from services.rss import RSSService
from services.extractors import Extractor
from services.scheduler_service import scheduler_service
from services.llm.gemini import gemini_llm
from sqlalchemy import text, func
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/news")
logger = logging.getLogger(__name__)


# ============================================================================
# FEED ENDPOINTS
# ============================================================================
@router.get("/feeds", response_model=List[RSSFeedResponse], tags=["Feed"])
async def get_feeds(db: Session = Depends(get_db)):
    """Get all configured RSS feeds."""
    feeds = db.query(RSSFeed).all()
    return [RSSFeedResponse.model_validate(feed) for feed in feeds]

@router.get("/feeds/logs", response_model=List[FeedFetchLogResponse], tags=["Feed"])
async def get_fetch_logs(
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get recent RSS fetch logs."""
    logs = db.query(FeedFetchLog).order_by(FeedFetchLog.fetch_timestamp.desc()).limit(limit).all()
    return [FeedFetchLogResponse.model_validate(log) for log in logs]

@router.get("/feeds/status", tags=["Feed"])
async def get_feeds_status(db: Session = Depends(get_db)):
    """Get status of all RSS feeds with optimized query."""

    # Subquery to get latest log per feed
    latest_logs_subq = (
        db.query(
            FeedFetchLog.feed_id,
            func.max(FeedFetchLog.fetch_timestamp).label('max_timestamp')
        )
        .group_by(FeedFetchLog.feed_id)
        .subquery()
    )

    # Main query with join
    results = (
        db.query(RSSFeed, FeedFetchLog)
        .outerjoin(
            latest_logs_subq,
            RSSFeed.id == latest_logs_subq.c.feed_id
        )
        .outerjoin(
            FeedFetchLog,
            (FeedFetchLog.feed_id == latest_logs_subq.c.feed_id) &
            (FeedFetchLog.fetch_timestamp == latest_logs_subq.c.max_timestamp)
        )
        .all()
    )

    feed_status = []
    for feed, latest_log in results:
        feed_status.append({
            "name": feed.name,
            "url": feed.url,
            "category": feed.category,
            "is_active": feed.is_active,
            "last_fetch": latest_log.fetch_timestamp if latest_log else None,
            "last_status": latest_log.status if latest_log else "never_fetched",
            "articles_processed": latest_log.articles_processed if latest_log else 0
        })

    return {"feeds": feed_status}


@router.post("/feeds/{feed_name}/toggle", tags=["Feed"])
async def toggle_feed_status(feed_name: str, db: Session = Depends(get_db)):
    """Toggle the active status of a feed."""
    service = RSSService(db)
    result = service.toggle_feed_status(feed_name)

    if result["status"] == "error":
        raise HTTPException(status_code=404, detail=result["message"])

    return result


@router.post("/feeds/{feed_name}/toggle-extraction", tags=["Feed"])
async def toggle_feed_extraction(feed_name: str, db: Session = Depends(get_db)):
    """Toggle the skip_extraction status of a feed. When enabled, article content extraction will be skipped for feeds that require subscription."""
    feed = db.query(RSSFeed).filter(RSSFeed.name == feed_name).first()

    if not feed:
        raise HTTPException(status_code=404, detail=f"Feed '{feed_name}' not found")

    feed.skip_extraction = not feed.skip_extraction
    db.commit()

    return {
        "status": "success",
        "feed_name": feed.name,
        "skip_extraction": feed.skip_extraction,
        "message": f"Content extraction {'disabled' if feed.skip_extraction else 'enabled'} for feed '{feed_name}'"
    }


@router.delete("/feeds/delete/{feed_name}", tags=["Feed"])
async def delete_feed(feed_name: str, db: Session = Depends(get_db)):
    """Delete a feed."""
    service = RSSService(db)
    result = service.delete_feed(feed_name)
    if result["status"] == "error":
        raise HTTPException(status_code=404, detail=result["message"])
    return result


@router.post("/feeds/add", tags=["Feed"])
async def add_feed(feed: RSSFeedCreate, db: Session = Depends(get_db)):
    """Add a feed."""
    db_feed = RSSFeed(**feed.model_dump())

    db.add(db_feed)
    db.commit()
    db.refresh(db_feed)
    return {"message": f"Feed {feed.name} added successfully"}


@router.patch("/feeds/{feed_name}", response_model=RSSFeedResponse, tags=["Feed"])
async def update_feed(feed_name: str, changes: RSSFeedUpdate, db: Session = Depends(get_db)):
    feed = db.query(RSSFeed).filter(RSSFeed.name == feed_name).first()
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")
    updates = changes.model_dump(exclude_unset=True)
    for field in ("name", "url", "is_active", "skip_extraction"):
        if field in updates and updates[field] is None:
            raise HTTPException(status_code=422, detail=f"{field} cannot be null")
    for field, value in updates.items():
        setattr(feed, field, value)
    db.commit()
    db.refresh(feed)
    return feed


@router.post("/fetch", tags=["Feed"])
async def fetch_all_feeds(db: Session = Depends(get_db)):
    """Fetch all RSS feeds."""
    service = RSSService(db)
    result = await service.fetch_all_feeds()
    return {"message": "Feed fetching completed", "result": result}


@router.post("/fetch/{feed_name}", tags=["Feed"])
async def fetch_specific_feed(feed_name: str, db: Session = Depends(get_db)):
    """Fetch a specific RSS feed."""   

    service = RSSService(db)
    feed = db.query(RSSFeed).filter(RSSFeed.name == feed_name).first()
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    result = await service.fetch_feed_async(feed)
    
    return {
        "feed_name": feed_name,
        **result
    }


# ============================================================================
# ARTICLE ENDPOINTS
# ============================================================================

@router.get("/articles", response_model=NewsArticleList, tags=["Article"])
async def get_articles(
    category: Optional[str] = Query(None, description="Filter by category"),
    source: Optional[str] = Query(None, description="Filter by source name"),
    feeds: Optional[str] = Query(None, description="Comma-separated list of feed names to filter by"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Articles per page"),
    db: Session = Depends(get_db)
):
    logger.info(f"---- Getting articles with filters: category={category}, source={source}, feeds={feeds}, page={page}, per_page={per_page} ----")
    """Get articles with optional filtering and pagination."""
    offset = (page - 1) * per_page
    
    # Build WHERE clause conditions
    where_conditions = ["rf.is_active = true"]
    params = {"offset": offset, "limit": per_page}
    
    if category:
        where_conditions.append("na.category = :category")
        params["category"] = category
    
    if source:
        where_conditions.append("rf.name = :source")
        params["source"] = source
    
    if feeds:
        feed_names = [name.strip() for name in feeds.split(',') if name.strip()]
        if feed_names:
            placeholders = ",".join([f":feed_{i}" for i in range(len(feed_names))])
            where_conditions.append(f"rf.name IN ({placeholders})")
            for i, feed_name in enumerate(feed_names):
                params[f"feed_{i}"] = feed_name
    
    where_clause = " AND ".join(where_conditions)
    
    # Count query
    count_sql = f"""
        SELECT COUNT(*) as total
        FROM news_articles na
        JOIN rss_feeds rf ON na.feed_id = rf.id
        WHERE {where_clause}
    """
    
    count_result = db.execute(text(count_sql), params).fetchone()
    total = count_result[0] if count_result else 0
    
    # Data query
    data_sql = f"""
        SELECT na.*, rf.name as feed_name
        FROM news_articles na
        JOIN rss_feeds rf ON na.feed_id = rf.id
        WHERE {where_clause}
        ORDER BY na.published_date DESC NULLS LAST, na.created_at DESC
        LIMIT :limit OFFSET :offset
    """
    
    result = db.execute(text(data_sql), params)
    rows = result.fetchall()
    
    # Convert rows directly to response dictionaries
    articles = []
    for row in rows:
        article_dict = {
            "id": row.id,
            "title": row.title,
            "link": row.link,
            "summary": row.summary,
            "content": row.content,
            "published_date": row.published_date,
            "feed_name": row.feed_name,
            "category": row.category,
            "image_url": row.image_url,
            "slug": row.slug,
            "author": row.author if hasattr(row, 'author') else None,
            "created_at": row.created_at,
            "updated_at": row.updated_at
        }
        articles.append(NewsArticleResponse(**article_dict))
    
    total_pages = (total + per_page - 1) // per_page
    print(f"---- Retrieved {len(articles)} articles out of {total} total ----")
    return NewsArticleList(
        articles=articles,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages
    )


@router.get("/articles/{article_id}", response_model=NewsArticleResponse, tags=["Article"])
async def get_article(article_id: int, db: Session = Depends(get_db)):
    "Get a specific article by ID. Automatically extracts content if missing."""
    logger = logging.getLogger("get_article")
    
    # Only get articles from active feeds
    article = db.query(NewsArticle).filter(
        NewsArticle.id == article_id,
        NewsArticle.feed_id.isnot(None)
    ).first()
    
    # Verify the feed is active
    if article and article.feed:
        if not article.feed.is_active:
            article = None
    
    if not article:
        raise HTTPException(status_code=404, detail="Article not found or feed is inactive")
    
    # Check if article has content, if not, extract it automatically
    # Skip extraction if the feed has skip_extraction enabled
    if not article.content or not article.content.strip():
        if article.feed and article.feed.skip_extraction:
            logger.info(f"Article {article_id} from feed '{article.feed.name}' has skip_extraction enabled, skipping automatic extraction")
            return article

        logger.info(f"Article {article_id} has no content, extracting automatically")

        if not article.link:
            logger.warning(f"Article {article_id} has no link, cannot extract content")
            return article

        try:
            extractor = Extractor()
            content, extracted_image_url = extractor.extract(article)

            updated = False

            # Update content if extracted
            if content:
                article.content = content
                updated = True
                logger.info(f"Successfully extracted content for article {article_id}")

            # Update image_url if extracted and missing
            if extracted_image_url and (not article.image_url or not article.image_url.strip()):
                article.image_url = extracted_image_url
                updated = True
                logger.info(f"Updated image URL for article {article_id}")

            # Update timestamp if any changes were made
            if updated:
                article.updated_at = datetime.now()
                db.commit()
                logger.info(f"Article {article_id} updated with extracted content")

        except Exception as e:
            logger.error(f"Error extracting content for article {article_id}: {e} ")
            logger.error(f'Stack trace: ', exc_info=True)
            # Continue and return the article even if extraction fails
    
    return article


@router.get("/articles/slug/{slug}", response_model=NewsArticleResponse, tags=["Article"])
async def get_article_by_slug(slug: str, db: Session = Depends(get_db)):
    """Get a specific article by slug. Automatically extracts content if missing."""
    logger = logging.getLogger("get_article_by_slug")
    
    # Only get articles from active feeds
    article = db.query(NewsArticle).filter(
        NewsArticle.slug == slug,
        NewsArticle.feed_id.isnot(None)
    ).first()
    
    # Verify the feed is active
    if article and article.feed:
        if not article.feed.is_active:
            article = None
    
    if not article:
        raise HTTPException(status_code=404, detail="Article not found or feed is inactive")
    
    # Check if article has content, if not, extract it automatically
    # Skip extraction if the feed has skip_extraction enabled
    if not article.content or not article.content.strip():
        if article.feed and article.feed.skip_extraction:
            logger.info(f"Article {article.id} (slug: {slug}) from feed '{article.feed.name}' has skip_extraction enabled, skipping automatic extraction")
            return article

        logger.info(f"Article {article.id} (slug: {slug}) has no content, extracting automatically")

        if not article.link:
            logger.warning(f"Article {article.id} has no link, cannot extract content")
            return article

        try:
            extractor = Extractor()
            content, extracted_image_url = extractor.extract(article)

            updated = False

            # Update content if extracted
            if content:
                article.content = content
                updated = True
                logger.info(f"Successfully extracted content for article {article.id}")

            # Update image_url if extracted and missing
            if extracted_image_url and (not article.image_url or not article.image_url.strip()):
                article.image_url = extracted_image_url
                updated = True
                logger.info(f"Updated image URL for article {article.id}")

            # Update timestamp if any changes were made
            if updated:
                article.updated_at = datetime.now()
                db.commit()
                logger.info(f"Article {article.id} updated with extracted content")

        except Exception as e:
            logger.error(f"Error extracting content for article {article.id}: {e}")
            # Continue and return the article even if extraction fails
    
    return article


@router.get("/articles/category/{category}", response_model=NewsArticleList, tags=["Article"])
async def get_articles_by_category(
    category: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """Get articles by the category inherited from their source feed."""
    offset = (page - 1) * per_page

    # Only get articles from active feeds
    query = db.query(NewsArticle).filter(
        NewsArticle.category == category,
        NewsArticle.feed_id.isnot(None)
    ).join(RSSFeed, NewsArticle.feed_id == RSSFeed.id).filter(
        RSSFeed.is_active == True
    )
    total = query.count()

    articles = query.order_by(NewsArticle.published_date.desc().nullslast(), NewsArticle.created_at.desc()) \
                   .offset(offset) \
                   .limit(per_page) \
                   .all()

    total_pages = (total + per_page - 1) // per_page

    return NewsArticleList(
        articles=[NewsArticleResponse.model_validate(article) for article in articles],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages
    )


@router.get("/search", response_model=NewsArticleList, tags=["Article"])
async def search_articles(
    query: str = Query("", description="Search query"),
    category: str = Query("all", description="Filter by category"),
    time_filter: str = Query("24h", description="Time filter"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Articles per page"),
    db: Session = Depends(get_db)
):
    """Search articles by query with optional filters."""
    if not query.strip():
        raise HTTPException(status_code=400, detail="Search query is required")
    
    offset = (page - 1) * per_page
    
    # Build search query - only search articles from active feeds
    search_query = db.query(NewsArticle).filter(
        NewsArticle.feed_id.isnot(None)
    ).join(RSSFeed, NewsArticle.feed_id == RSSFeed.id).filter(
        RSSFeed.is_active == True,
        NewsArticle.title.contains(query) | 
        NewsArticle.summary.contains(query) |
        NewsArticle.content.contains(query)
    )
    
    # Apply category filter
    if category != "all":
        search_query = search_query.filter(NewsArticle.category == category)
    
    # Apply time filter
    if time_filter == "24h":
        time_threshold = datetime.now() - timedelta(hours=24)
        search_query = search_query.filter(NewsArticle.created_at >= time_threshold)
    elif time_filter == "7d":
        time_threshold = datetime.now() - timedelta(days=7)
        search_query = search_query.filter(NewsArticle.created_at >= time_threshold)
    elif time_filter == "30d":
        time_threshold = datetime.now() - timedelta(days=30)
        search_query = search_query.filter(NewsArticle.created_at >= time_threshold)
    
    # Get total count
    total = search_query.count()
    
    # Get paginated results
    articles = search_query.order_by(NewsArticle.published_date.desc().nullslast(), NewsArticle.created_at.desc()) \
                          .offset(offset) \
                          .limit(per_page) \
                          .all()
    
    total_pages = (total + per_page - 1) // per_page
    
    return NewsArticleList(
        articles=[NewsArticleResponse.model_validate(article) for article in articles],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages
    )


@router.post("/articles/{article_id}/extract", tags=["Article"], response_model=NewsArticleResponse)
async def extract_article_content(article_id: int, db: Session = Depends(get_db)):
    """Extract content for a specific article."""
    article = db.query(NewsArticle).filter(NewsArticle.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    # Check if feed has skip_extraction enabled
    if article.feed and article.feed.skip_extraction:
        raise HTTPException(
            status_code=403,
            detail=f"Content extraction is disabled for feed '{article.feed.name}'. This feed requires subscription access."
        )

    if not article.link:
        raise HTTPException(status_code=400, detail="Article has no link to extract content from")

    try:
        extractor = Extractor()
        content, extracted_image_url = extractor.extract(article)

        updated = False

        # Update content if extracted
        if content:
            article.content = content
            updated = True
            logger.info(f"Successfully extracted content for article {article_id}")

        # Update image_url if extracted and missing
        if extracted_image_url and (not article.image_url or article.image_url.strip() == ""):
            article.image_url = extracted_image_url
            updated = True
            logger.info(f"Updated image URL for article {article_id}")

        # Update timestamp if any changes were made
        if updated:
            article.updated_at = datetime.now()
            db.commit()
            logger.info(f"Article {article_id} updated with extracted content")
        else:
            logger.warning(f"No content extracted for article {article_id}")

        return NewsArticleResponse.model_validate(article)

    except Exception as e:
        logger.error(f"Error extracting content for article {article_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error extracting content: {str(e)}")


@router.post("/articles/{article_id}/summarize", tags=["Article"], response_model=NewsArticleResponse)
async def summarize_article_content(article_id: int, db: Session = Depends(get_db)):
    """Generate AI summary for a specific article using Gemini API."""
    article = db.query(NewsArticle).filter(NewsArticle.id == article_id).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    # Check if article has content to summarize
    if not article.content or not article.content.strip():
        raise HTTPException(
            status_code=400,
            detail="Article has no content to summarize. Extract content first using /articles/{article_id}/extract"
        )

    try:
        # Generate summary using Gemini
        summary = gemini_llm.summarize_article(article.title, article.content)

        if summary:
            article.summary = summary
            article.updated_at = datetime.now()
            db.commit()
            logger.info(f"Successfully generated AI summary for article {article_id}")
            return NewsArticleResponse.model_validate(article)
        else:
            logger.warning(f"Failed to generate summary for article {article_id}")
            raise HTTPException(status_code=500, detail="Failed to generate summary from Gemini API")

    except Exception as e:
        logger.error(f"Error generating summary for article {article_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating summary: {str(e)}")


@router.post("/articles/summarize/batch", tags=["Article"])
async def summarize_articles_batch(
    article_ids: List[int],
    db: Session = Depends(get_db)
):
    """Generate AI summaries for multiple articles in batch."""
    if not article_ids:
        raise HTTPException(status_code=400, detail="No article IDs provided")

    if len(article_ids) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 articles per batch")

    # Fetch articles
    articles = db.query(NewsArticle).filter(NewsArticle.id.in_(article_ids)).all()

    if not articles:
        raise HTTPException(status_code=404, detail="No articles found")

    # Prepare articles for batch summarization
    articles_data = [
        {
            'id': article.id,
            'title': article.title,
            'content': article.content
        }
        for article in articles
        if article.content and article.content.strip()
    ]

    if not articles_data:
        raise HTTPException(status_code=400, detail="No articles with content to summarize")

    try:
        # Generate summaries
        summaries = gemini_llm.summarize_batch(articles_data)

        # Update articles with summaries
        updated_count = 0
        for article in articles:
            if article.id in summaries:
                article.summary = summaries[article.id]
                article.updated_at = datetime.now()
                updated_count += 1

        db.commit()
        logger.info(f"Successfully generated {updated_count} summaries in batch")

        return {
            "status": "success",
            "total_requested": len(article_ids),
            "total_found": len(articles),
            "total_summarized": updated_count,
            "summaries": summaries
        }

    except Exception as e:
        logger.error(f"Error in batch summarization: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating summaries: {str(e)}")


# ============================================================================
# SCHEDULER MANAGEMENT ENDPOINTS
# ============================================================================

@router.get("/scheduler/status", tags=["Scheduler Management"])
async def get_scheduler_status():
    """Get scheduler status."""
    return {"status": "running" if scheduler_service.scheduler.running else "stopped"}


@router.post("/scheduler/start", tags=["Scheduler Management"])
async def start_scheduler():
    """Start the scheduler."""
    scheduler_service.start()
    return {"message": "Scheduler started"}


@router.post("/scheduler/stop", tags=["Scheduler Management"])
async def stop_scheduler():
    """Stop the scheduler."""
    scheduler_service.stop()
    return {"message": "Scheduler stopped"}




# ============================================================================
# ADMIN ENDPOINTS
# ============================================================================
# TODO: Add authentication

@router.delete("/admin/cleanup/all", tags=["Admin"])
async def cleanup_all_data(db: Session = Depends(get_db)):
    """Clean up all data from the database."""
    service = RSSService(db)
    await service.cleanup_all_data()
    return {"message": "All data cleaned up successfully"}


@router.delete("/admin/cleanup/feed/{feed_name}", tags=["Admin"])
async def cleanup_feed_data(feed_name: str, db: Session = Depends(get_db)):
    """Clean up data for a specific feed."""
    service = RSSService(db)
    await service.cleanup_feed_data(feed_name)
    return {"message": f"Data for feed '{feed_name}' cleaned up successfully"}


@router.delete("/admin/cleanup/article/{article_id}", tags=["Admin"])
async def delete_article_content(article_id: int, db: Session = Depends(get_db)):
    """Delete content for a specific article."""
    service = RSSService(db)
    await service.delete_article_content(article_id)
    return {"message": f"Content for article {article_id} deleted successfully"}


# ============================================================================
# STATS ENDPOINTS
# ============================================================================

@router.get("/health", response_model=HealthCheckResponse, tags=["Stats"])
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint."""
    try:
        # Test database connection
        db.execute(text("SELECT 1"))
        database_connected = True
        
        # Get counts
        feeds_count = db.query(RSSFeed).count()
        articles_count = db.query(NewsArticle).count()
        
    except Exception as e:
        database_connected = False
        feeds_count = 0
        articles_count = 0
    
    return HealthCheckResponse(
        status="healthy",
        timestamp=datetime.now(),
        database_connected=database_connected,
        feeds_count=feeds_count,
        articles_count=articles_count
    )


@router.get("/stats", tags=["Stats"])
async def get_stats(db: Session = Depends(get_db)):
    """Get statistics with optimized queries."""

    # Single query for category stats
    category_stats = db.query(
        NewsArticle.category,
        func.count(NewsArticle.id).label('count')
    ).group_by(NewsArticle.category).all()

    articles_by_category = {stat.category: stat.count for stat in category_stats}
    total_articles = sum(articles_by_category.values())  # Reuse instead of separate query

    # Source stats query
    source_stats = db.query(
        NewsArticle.feed_id.label('source_name'),
        func.count(NewsArticle.id).label('count')
    ).group_by(NewsArticle.feed_id).all()

    articles_by_source = {stat.source_name: stat.count for stat in source_stats}

    # Recent articles
    recent_articles = db.query(NewsArticle).order_by(
        NewsArticle.created_at.desc()
    ).limit(5).all()

    # Combined feed counts in single query
    from sqlalchemy import Integer
    feed_counts = db.query(
        func.count(RSSFeed.id).label('total'),
        func.sum(func.cast(RSSFeed.is_active, Integer)).label('active')
    ).first()

    return {
        "total_articles": total_articles,
        "articles_by_category": articles_by_category,
        "articles_by_source": articles_by_source,
        "recent_articles": [
            {
                "id": article.id,
                "title": article.title,
                "source_name": article.feed_id,
                "created_at": article.created_at
            }
            for article in recent_articles
        ],
        "active_feeds": feed_counts.active or 0,
        "total_feeds": feed_counts.total or 0,
        "last_updated": datetime.now()
    }

