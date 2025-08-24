from fastapi import APIRouter, Query
from typing import Optional, Dict, Any
from datetime import datetime

from src import config
from src.backfill import start_collect, stop_collect, start_summarize, stop_summarize, get_status

router = APIRouter(prefix="/admin")


def _parse_date(d: Optional[str]) -> Optional[datetime]:
    if not d:
        return None
    d = d.strip()
    # Accept DD.MM.YYYY or YYYY-MM-DD
    try:
        dt = datetime.strptime(d, "%d.%m.%Y")
        return dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=config.APP_TZ)
    except Exception:
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            return dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=config.APP_TZ)
        except Exception:
            return None


@router.get("/backfill/status", response_model=Dict[str, Any])
async def admin_backfill_status():
    return get_status()

# Public, unauthenticated mirror for bot autodiscovery (CSP/middleware allows)
public_router = APIRouter()

@public_router.get("/backfill/status-public", response_model=Dict[str, Any])
async def backfill_status_public():
    return get_status()


@router.post("/backfill/collect/start", response_model=Dict[str, Any])
async def admin_collect_start(until: Optional[str] = Query(None, description="DD.MM.YYYY or YYYY-MM-DD")):
    dt = _parse_date(until) or config.BASE_AUTO_UPDATE_TARGET_DT
    start_collect(until_dt=dt)
    return get_status()


@router.post("/backfill/collect/stop", response_model=Dict[str, Any])
async def admin_collect_stop():
    stop_collect()
    return get_status()


@router.post("/backfill/summarize/start", response_model=Dict[str, Any])
async def admin_summarize_start(
    until: Optional[str] = Query(None, description="DD.MM.YYYY or YYYY-MM-DD"),
    model: Optional[str] = Query(None, description="gemini|mistral"),
):
    dt = _parse_date(until) or config.BASE_AUTO_UPDATE_TARGET_DT
    start_summarize(until_dt=dt, model=model or config.BASE_AUTO_SUM_MODEL)
    return get_status()


@router.post("/backfill/summarize/stop", response_model=Dict[str, Any])
async def admin_summarize_stop():
    stop_summarize()
    return get_status()
