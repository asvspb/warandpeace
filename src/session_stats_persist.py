from __future__ import annotations

from typing import Any, Dict, Optional, List
from datetime import datetime, timezone

try:
    from prometheus_client import REGISTRY  # type: ignore
except Exception:  # pragma: no cover
    REGISTRY = None  # type: ignore

# Support both package and module execution contexts
try:  # pragma: no cover - import style may vary in runtime
    from . import config  # type: ignore
    from . import database  # type: ignore
except Exception:  # pragma: no cover
    import config  # type: ignore
    import database  # type: ignore


def _safe_int(x: Any) -> int:
    try:
        return int(float(x))
    except Exception:
        return 0


def _scrape_session_counters() -> Dict[str, Optional[float]]:
    """Scrape in-process Prometheus registry to get session counters we need.

    Returns dict with keys:
      - http_total_session: int
      - session_start_ts: float | None
    """
    http_total = 0
    session_start_ts: Optional[float] = None

    if REGISTRY is None:
        return {"http_total_session": 0, "session_start_ts": None}

    try:
        for fam in REGISTRY.collect():  # type: ignore[attr-defined]
            name = getattr(fam, "name", "")
            if name == "external_http_requests_total":
                try:
                    http_total = int(sum(_safe_int(s.value) for s in fam.samples))
                except Exception:
                    http_total = 0
            elif name == "session_start_time_seconds":
                try:
                    samples = list(fam.samples)
                    if samples:
                        session_start_ts = float(samples[-1].value)
                except Exception:
                    session_start_ts = None
    except Exception:
        pass
    return {"http_total_session": http_total, "session_start_ts": session_start_ts}


def _tokens_today_from_db(day_utc: str) -> Dict[str, int]:
    try:
        rows: List[Dict[str, Any]] = database.get_api_usage_daily_for_day(day_utc)
    except Exception:
        rows = []
    tokens_in = sum(int(r.get("tokens_in_total") or 0) for r in rows)
    tokens_out = sum(int(r.get("tokens_out_total") or 0) for r in rows)
    return {"tokens_in": tokens_in, "tokens_out": tokens_out}


def persist_session_stats_once() -> Dict[str, Any]:
    """Persist daily session stats into SQLite if enabled.

    - Aggregates HTTP requests (from session counter) idempotently with local state baseline
    - Uses DB to compute robust per-day articles count
    - Uses API usage daily aggregates for tokens
    """
    result: Dict[str, Any] = {"enabled": False, "updated": False}
    if not getattr(config, "SESSION_STATS_ENABLED", False):
        return result
    result["enabled"] = True

    today = datetime.now(timezone.utc).date().isoformat()
    scraped = _scrape_session_counters()
    http_total_session = int(scraped.get("http_total_session") or 0)
    session_start_ts = scraped.get("session_start_ts")

    # State
    state = database.get_session_stats_state()
    last_start = state.get("last_session_start")
    last_http = int(state.get("last_http_counter") or 0)
    # Detect restart: reset baseline
    if session_start_ts is not None:
        try:
            if (last_start is None) or (float(last_start) != float(session_start_ts)):
                last_http = 0
        except Exception:
            last_http = 0

    # Compute delta since last flush within this session
    delta_http = max(0, http_total_session - last_http)

    # Current day aggregates from other sources
    tokens = _tokens_today_from_db(today)

    # Articles: count by published_at day
    try:
        articles = database.count_articles_for_day(today)
    except Exception:
        articles = 0

    # Get existing persisted for today and accumulate HTTP
    try:
        prev = database.get_session_stats_daily_for_day(today) or {}
        prev_http = int(prev.get("http_requests_total") or 0)
    except Exception:
        prev_http = 0
    new_http_total = prev_http + delta_http

    try:
        database.upsert_session_stats_daily(
            today,
            new_http_total,
            int(articles or 0),
            int(tokens.get("tokens_in", 0)),
            int(tokens.get("tokens_out", 0)),
        )
        # Update state with current baseline
        database.update_session_stats_state(session_start_ts, http_total_session)
        result.update({
            "updated": True,
            "day": today,
            "http_delta": delta_http,
            "http_total": new_http_total,
            "articles": articles,
            "tokens_in": tokens.get("tokens_in", 0),
            "tokens_out": tokens.get("tokens_out", 0),
        })
    except Exception:
        # Best-effort; no raise
        result["updated"] = False
    return result
