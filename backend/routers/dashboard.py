"""Read-only dashboard page and snapshot endpoint."""

from pathlib import Path

from fastapi import APIRouter, Depends, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from config.settings import settings
from database import get_db
from schemas import DashboardResponse
from services.dashboard import get_dashboard_snapshot
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
def dashboard_snapshot(response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return get_dashboard_snapshot(db, scheduler_service, settings)
