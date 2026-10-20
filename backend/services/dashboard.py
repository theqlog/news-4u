"""Database aggregates for the ingestion dashboard."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import Date, and_, case, cast, func

from models import FeedFetchLog, NewsArticle, RSSFeed
from schemas import (
    DashboardArticleCounts, DashboardFeed, DashboardFetch, DashboardResponse,
    DashboardScheduler, DashboardSummary,
)
from services.processing import extraction_eligible_condition, missing_content_condition


def article_count_columns(max_retry):
    missing = missing_content_condition()
    disabled = and_(missing, RSSFeed.skip_extraction.is_(True))
    exhausted = and_(
        missing, RSSFeed.skip_extraction.is_(False),
        func.coalesce(NewsArticle.retry_count, 0) >= max_retry,
    )
    return [
        func.count(NewsArticle.id).label("total"),
        func.count(case((~missing, NewsArticle.id))).label("with_content"),
        func.count(case((missing, NewsArticle.id))).label("missing_content"),
        func.count(case((extraction_eligible_condition(max_retry), NewsArticle.id))).label("awaiting_extraction"),
        func.count(case((disabled, NewsArticle.id))).label("extraction_disabled"),
        func.count(case((exhausted, NewsArticle.id))).label("retry_limit_reached"),
    ]


def article_counts(row):
    counts = {column: getattr(row, column) for column in (
        "total", "with_content", "missing_content", "awaiting_extraction",
        "extraction_disabled", "retry_limit_reached",
    )}
    counts["not_eligible"] = counts["missing_content"] - sum(
        counts[key] for key in ("awaiting_extraction", "extraction_disabled", "retry_limit_reached")
    )
    return DashboardArticleCounts(**counts)


def get_dashboard_snapshot(db, scheduler, settings, days=7):
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=days - 1)
    dates = [(start + timedelta(days=index)).date() for index in range(days)]
    article_day = cast(func.timezone("UTC", NewsArticle.created_at), Date)
    daily_rows = db.query(NewsArticle.feed_id, article_day.label("day"), func.count(NewsArticle.id).label("count")).filter(
        NewsArticle.created_at >= start,
        NewsArticle.created_at < today + timedelta(days=1),
    ).group_by(NewsArticle.feed_id, article_day).all()
    daily_counts = {(row.feed_id, row.day): row.count for row in daily_rows}
    columns = article_count_columns(settings.ARTICLE_EXTRACTION_MAX_RETRY)
    # Include orphaned articles in global totals, even though they cannot be extracted.
    totals = db.query(*columns).select_from(NewsArticle).outerjoin(
        RSSFeed, NewsArticle.feed_id == RSSFeed.id,
    ).one()
    per_feed = db.query(NewsArticle.feed_id, *columns).select_from(NewsArticle).outerjoin(
        RSSFeed, NewsArticle.feed_id == RSSFeed.id,
    ).group_by(NewsArticle.feed_id).all()
    counts_by_feed = {row.feed_id: article_counts(row) for row in per_feed}

    ranked_logs = db.query(
        FeedFetchLog.id,
        func.row_number().over(
            partition_by=FeedFetchLog.feed_id,
            order_by=(FeedFetchLog.fetch_timestamp.desc().nullslast(), FeedFetchLog.id.desc()),
        ).label("rank"),
    ).subquery()
    latest_logs = db.query(FeedFetchLog).join(
        ranked_logs, FeedFetchLog.id == ranked_logs.c.id,
    ).filter(ranked_logs.c.rank == 1).all()
    logs_by_feed = {log.feed_id: log for log in latest_logs}

    feeds = []
    for feed in db.query(RSSFeed).order_by(RSSFeed.name, RSSFeed.id).all():
        log = logs_by_feed.get(feed.id)
        feeds.append(DashboardFeed(
            id=feed.id, name=feed.name, urls=feed.url, category=feed.category,
            is_active=bool(feed.is_active), skip_extraction=bool(feed.skip_extraction),
            articles=counts_by_feed.get(feed.id, DashboardArticleCounts()),
            daily_articles=[daily_counts.get((feed.id, day), 0) for day in dates],
            latest_fetch=DashboardFetch(
                timestamp=log.fetch_timestamp, status=log.status,
                entries_found=log.articles_found or 0,
                valid_entries_submitted=log.articles_processed or 0,
                duration_ms=log.execution_time_ms, error=log.error_message,
            ) if log else None,
        ))

    return DashboardResponse(
        snapshot_at=now,
        daily_dates=dates,
        summary=DashboardSummary(
            **article_counts(totals).model_dump(), total_feeds=len(feeds),
            active_feeds=sum(feed.is_active for feed in feeds),
        ),
        feeds=feeds,
        scheduler=DashboardScheduler(enabled=settings.SCHEDULE_ENABLE, **scheduler.get_job_status()),
    )
