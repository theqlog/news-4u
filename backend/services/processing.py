"""Shared definitions for stored content and scheduled extraction eligibility."""

from sqlalchemy import and_, func, or_

from models import NewsArticle, RSSFeed

WHITESPACE = " \t\r\n\v\f"


def has_content(content):
    return content is not None and content.strip() not in ("", "None")


def missing_content_condition():
    return or_(
        NewsArticle.content.is_(None),
        func.btrim(NewsArticle.content, WHITESPACE).in_(("", "None")),
    )


def extraction_eligible_condition(max_retry):
    # Active controls RSS fetching, not extraction of already stored articles.
    return and_(
        missing_content_condition(),
        RSSFeed.id.isnot(None),
        RSSFeed.skip_extraction.is_(False),
        func.coalesce(NewsArticle.retry_count, 0) < max_retry,
        NewsArticle.link.isnot(None),
        func.btrim(NewsArticle.link, WHITESPACE) != "",
    )
