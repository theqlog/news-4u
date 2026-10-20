"""Dashboard page, metrics, and feed management."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from config.settings import settings
from database import get_db
from models import FeedFetchLog, NewsArticle, RSSFeed
from schemas import DashboardFeedInput, DashboardResponse, RSSFeedResponse
from services.dashboard import get_dashboard_snapshot
from services.rss import RSSService
from services.scheduler_service import scheduler_service

router = APIRouter()
ASSETS = Path(__file__).resolve().parent.parent / "dashboard"


@router.get("/dashboard", include_in_schema=False)
def dashboard_page():
    return FileResponse(ASSETS / "index.html", headers={"Cache-Control": "no-store"})


@router.get("/dashboard/style.css", include_in_schema=False)
def dashboard_styles():
    return FileResponse(ASSETS / "style.css", media_type="text/css")


@router.get("/dashboard/app.js", include_in_schema=False)
def dashboard_script():
    return FileResponse(ASSETS / "app.js", media_type="text/javascript")


@router.get("/api/news/dashboard", response_model=DashboardResponse, tags=["Dashboard"])
def dashboard_snapshot(response: Response, days: int = Query(7, ge=1, le=30), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return get_dashboard_snapshot(db, scheduler_service, settings, days)


def require_feed(db, feed_id):
    feed = db.get(RSSFeed, feed_id)
    if feed is None:
        raise HTTPException(status_code=404, detail="Feed not found")
    return feed


def save_feed(db, feed):
    try:
        db.add(feed)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A feed with this name already exists")
    db.refresh(feed)
    return feed


@router.post("/api/news/dashboard/feeds", response_model=RSSFeedResponse, status_code=201, tags=["Dashboard"])
def create_dashboard_feed(data: DashboardFeedInput, db: Session = Depends(get_db)):
    return save_feed(db, RSSFeed(**data.model_dump()))


@router.put("/api/news/dashboard/feeds/{feed_id}", response_model=RSSFeedResponse, tags=["Dashboard"])
def update_dashboard_feed(feed_id: int, data: DashboardFeedInput, db: Session = Depends(get_db)):
    feed = require_feed(db, feed_id)
    for key, value in data.model_dump().items():
        setattr(feed, key, value)
    return save_feed(db, feed)


@router.delete("/api/news/dashboard/feeds/{feed_id}", tags=["Dashboard"])
def delete_dashboard_feed(feed_id: int, db: Session = Depends(get_db)):
    feed = require_feed(db, feed_id)
    # Retain collected articles and history without the removed source association.
    db.query(NewsArticle).filter(NewsArticle.feed_id == feed_id).update({"feed_id": None}, synchronize_session=False)
    db.query(FeedFetchLog).filter(FeedFetchLog.feed_id == feed_id).update({"feed_id": None}, synchronize_session=False)
    db.delete(feed)
    db.commit()
    return {"message": "Feed removed. Existing articles and fetch logs were retained without a source."}


@router.post("/api/news/dashboard/feeds/{feed_id}/refresh", tags=["Dashboard"])
async def refresh_dashboard_feed(feed_id: int, db: Session = Depends(get_db)):
    feed = require_feed(db, feed_id)
    return await RSSService(db).fetch_feed_async(feed)
