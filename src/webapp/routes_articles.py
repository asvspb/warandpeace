
import os
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from datetime import datetime, date, timedelta
import math

from src.webapp import services
from src.async_parser import fetch_articles_for_date
from src.parser import get_article_text
from src.database import upsert_raw_article
import asyncio
import threading
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

router = APIRouter()
# Resolve absolute templates path to be robust under pytest CWDs
import os as _os
_BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
_TEMPLATES_DIR = _os.path.join(_BASE_DIR, "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

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
    yesterday = today - timedelta(days=1)
    calendar_data = services.get_month_calendar_data(today.year, today.month)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "stats": stats,
            "calendar": calendar_data,
            "today_str": today.isoformat(),
            "yesterday_str": yesterday.isoformat(),
        },
    )

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
    # Ensure stable shape for tests that may not expect prev/next
    calendar_data.setdefault('prev', {'year': y, 'month': m})
    calendar_data.setdefault('next', {'year': y, 'month': m})
    calendar_data.setdefault('month_name', str(m))
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
    return templates.TemplateResponse(
        "calendar.html",
        {
            "request": request,
            "calendar": calendar_data,
            "today_str": today.isoformat(),
        },
    )


@router.get("/day/{day_iso}", response_class=HTMLResponse)
async def daily_feed(request: Request, day_iso: str):
    """Renders the daily news feed for a given date (YYYY-MM-DD)."""
    redir = _require_admin_session(request)
    if redir:
        return redir
    articles = services.get_daily_articles(day_iso)
    # Quick filter helpers
    today = date.today()
    yesterday = today - timedelta(days=1)
    return templates.TemplateResponse(
        "daily_feed.html",
        {
            "request": request,
            "day": day_iso,
            "articles": articles,
            "today_str": today.isoformat(),
            "yesterday_str": yesterday.isoformat(),
        },
    )


@router.post("/day/{day_iso}/ingest")
async def ingest_day(request: Request, day_iso: str):
    """Triggers ingestion of all articles for a specific day.

    Downloads article texts and upserts them into the database.
    Returns immediately with a simple JSON status. Work runs in a background thread.
    """
    # Admin session enforcement
    redir = _require_admin_session(request)
    if redir:
        # Mirror auth style used elsewhere for JSON endpoints
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Validate date
    try:
        target_date = datetime.strptime(day_iso, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    def _worker():
        try:
            pairs = asyncio.run(fetch_articles_for_date(target_date))
            for title, link in pairs:
                try:
                    text = get_article_text(link) or ""
                    if not text:
                        continue
                    # Persist at start of the day to group by date properly
                    ts = f"{target_date.isoformat()} 00:00:00"
                    upsert_raw_article(link, title, ts, text)
                except Exception:
                    # Swallow per-item errors to allow others to proceed
                    pass
            # Best-effort: notify live dashboards to refresh
            try:
                from src.webapp.server import _sse_broadcast  # type: ignore
                _sse_broadcast({"type": "backfill_updated"})
            except Exception:
                pass
        except Exception:
            # Background worker should not crash the app
            pass

    t = threading.Thread(target=_worker, name=f"ingest-{day_iso}", daemon=True)
    t.start()
    return {"status": "ok", "started": True, "date": day_iso}


@router.post("/articles/{article_id}/summarize")
async def summarize_article(request: Request, article_id: int):
    """Generate a summary for a single article and persist it.

    Returns JSON {ok: true, summary_text: str} on success.
    """
    # Admin session enforcement for JSON endpoint
    redir = _require_admin_session(request)
    if redir:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Fetch article
    try:
        from src.database import get_db_connection, set_article_summary
    except Exception:
        from database import get_db_connection, set_article_summary  # type: ignore

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, url, title, content, published_at FROM articles WHERE id = ?",
                (int(article_id),),
            )
            row = cur.fetchone()
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"db_error: {str(e)[:120]}"}, status_code=500)

    if not row:
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)

    url = row["url"]
    content = row.get("content") if hasattr(row, "get") else row[3]
    title = row.get("title") if hasattr(row, "get") else row[2]
    published_at = row.get("published_at") if hasattr(row, "get") else row[4]

    # Ensure we have content
    text = content or ""
    if not text:
        try:
            from src.parser import get_article_text as _get_text
        except Exception:
            from parser import get_article_text as _get_text  # type: ignore
        try:
            text = _get_text(url) or ""
        except Exception:
            text = ""
        # Best-effort: persist fetched content
        if text:
            try:
                with get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE articles SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (text, int(article_id)),
                    )
                    conn.commit()
            except Exception:
                pass

    if not text:
        return JSONResponse({"ok": False, "error": "no_content"}, status_code=400)

    # Summarize
    try:
        try:
            from src import summarizer as _summ
        except Exception:
            import summarizer as _summ  # type: ignore
        summary = _summ.summarize_text_local(text)
    except Exception as e:
        summary = None

    if not summary:
        return JSONResponse({"ok": False, "error": "summarization_failed"}, status_code=502)

    # Persist summary
    try:
        set_article_summary(int(article_id), summary)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"persist_failed: {str(e)[:120]}"}, status_code=500)

    try:
        # Notify dashboards/UI via SSE (best-effort)
        from src.webapp.server import _sse_broadcast  # type: ignore
        _sse_broadcast({"type": "article_summarized", "article_id": int(article_id)})
    except Exception:
        pass

    return JSONResponse({"ok": True, "summary_text": summary})

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


@router.get("/range", response_class=HTMLResponse)
async def range_feed(request: Request, days: int = Query(7, ge=1, le=31)):
    """Renders aggregated feed for the last N days (including today)."""
    redir = _require_admin_session(request)
    if redir:
        return redir
    groups = services.get_articles_range(days)
    return templates.TemplateResponse("range_feed.html", {"request": request, "days": int(days), "groups": groups})

@router.get("/stats", response_class=HTMLResponse)
async def session_stats(request: Request):
    """Renders session stats dashboard for the current process session."""
    redir = _require_admin_session(request)
    if redir:
        return redir
    stats = services.get_session_stats()
    return templates.TemplateResponse("session_stats.html", {"request": request, "stats": stats})


@router.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    """Simple admin panel page to control backfill workers."""
    redir = _require_admin_session(request)
    if redir:
        return redir
    return templates.TemplateResponse("admin.html", {"request": request})


@router.get("/stats.json")
async def session_stats_json(request: Request):
    """Returns JSON for the current session stats for logged-in admins.

    If not authorized, return 401 JSON instead of HTML redirect to keep fetch() semantics.
    """
    try:
        is_admin = bool(request.session.get("admin"))
    except Exception:
        is_admin = False
    if not is_admin:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse(services.get_session_stats())


@router.get("/stats/history", response_class=HTMLResponse)
async def session_stats_history(request: Request, days: int = Query(14, ge=1, le=90)):
    """Renders daily history of session stats from SQLite persistence."""
    redir = _require_admin_session(request)
    if redir:
        return redir
    hist = services.get_session_stats_history(days=days)
    return templates.TemplateResponse("session_stats_history.html", {"request": request, "hist": hist, "days": days})


@router.get("/stats/history.json")
async def session_stats_history_json(days: int = Query(14, ge=1, le=90)):
    """Returns JSON daily history for charts (admin-only via middleware)."""
    return JSONResponse(services.get_session_stats_history(days=days))
