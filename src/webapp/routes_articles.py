
import os
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from datetime import datetime, date
import math

from src.webapp import services
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()
templates = Jinja2Templates(directory="src/webapp/templates")

def _require_admin_session(request: Request):
    mode = os.getenv("WEB_AUTH_MODE", "basic").strip().lower()
    webauthn_enforce = os.getenv("WEB_WEBAUTHN_ENFORCE", "false").lower() == "true"
    if mode == "webauthn" and webauthn_enforce:
        if not request.session.get("admin"):
            # redirect to login page
            return RedirectResponse(url="/login", status_code=303)
    return None

@router.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Renders the main dashboard page with calendar of current month."""
    redir = _require_admin_session(request)
    if redir:
        return redir
    stats = services.get_dashboard_stats()
    today = date.today()
    calendar_data = services.get_month_calendar_data(today.year, today.month)
    return templates.TemplateResponse("index.html", {"request": request, "stats": stats, "calendar": calendar_data})

@router.get("/articles", response_class=HTMLResponse)
async def list_articles(
    request: Request,
    year: Optional[int] = None,
    month: Optional[int] = None,
):
    """Replaced: render calendar view instead of list."""
    redir = _require_admin_session(request)
    if redir:
        return redir
    today = date.today()
    y = year or today.year
    m = month or today.month
    calendar_data = services.get_month_calendar_data(y, m)
    return templates.TemplateResponse("calendar.html", {"request": request, "calendar": calendar_data})


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_view(request: Request, year: Optional[int] = None, month: Optional[int] = None):
    """Renders the calendar view for a given month (defaults to current)."""
    redir = _require_admin_session(request)
    if redir:
        return redir
    today = date.today()
    y = year or today.year
    m = month or today.month
    calendar_data = services.get_month_calendar_data(y, m)
    return templates.TemplateResponse("calendar.html", {"request": request, "calendar": calendar_data})


@router.get("/day/{day_iso}", response_class=HTMLResponse)
async def daily_feed(request: Request, day_iso: str):
    """Renders the daily news feed for a given date (YYYY-MM-DD)."""
    redir = _require_admin_session(request)
    if redir:
        return redir
    articles = services.get_daily_articles(day_iso)
    return templates.TemplateResponse("daily_feed.html", {"request": request, "day": day_iso, "articles": articles})

@router.get("/articles/{article_id}", response_class=HTMLResponse)
async def read_article(
    request: Request, 
    article_id: int
):
    """Renders the detail page for a single article."""
    redir = _require_admin_session(request)
    if redir:
        return redir
    article = services.get_article_by_id(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return templates.TemplateResponse("article_detail.html", {"request": request, "article": article})


@router.get("/stats", response_class=HTMLResponse)
async def session_stats(request: Request):
    """Renders session stats dashboard for the current process session."""
    redir = _require_admin_session(request)
    if redir:
        return redir
    stats = services.get_session_stats()
    return templates.TemplateResponse("session_stats.html", {"request": request, "stats": stats})
