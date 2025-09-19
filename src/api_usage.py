from __future__ import annotations

import threading
import hashlib
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple, Any

# Support both package and module execution contexts
try:  # When imported as part of the 'src' package
    from . import config  # type: ignore
    from . import database  # type: ignore
except Exception:  # When running as a script or via bare imports
    import config  # type: ignore
    import database  # type: ignore


# ---------------- Types ----------------

@dataclass
class ApiUsageEvent:
    ts_utc: str
    provider: str
    model: Optional[str]
    api_key_hash: Optional[str]
    endpoint: Optional[str]
    req_count: int
    success: bool
    http_status: Optional[int]
    latency_ms: Optional[int]
    tokens_in: int
    tokens_out: int
    cost_usd: float
    error_code: Optional[str]
    extra_json: Optional[str]


# ---------------- Session / buffer ----------------

_lock = threading.Lock()
_events_buffer: List[ApiUsageEvent] = []
# (provider, model, api_key_hash) -> counters
_session_counters: Dict[Tuple[Optional[str], Optional[str], Optional[str]], Dict[str, float]] = {}
_session_started_at = datetime.now(timezone.utc)
_session_id: Optional[str] = None


# ---------------- Cost estimation ----------------

# Simple price map per 1k tokens, by provider/model. Extend as needed.
# Values are fallback-friendly; if model not present, cost=0.0
_PRICE_PER_1K: Dict[str, Dict[str, Tuple[float, float]]] = {
    # provider -> model -> (price_in_usd_per_1k, price_out_usd_per_1k)
    # Example placeholders; set to 0 by default per plan
    "gemini": {
        # "models/gemini-1.5-flash-latest": (0.0, 0.0),
    },
    "mistral": {
        # "mistral-large-latest": (0.0, 0.0),
    },
}


def estimate_event_cost_usd(provider: str, model: Optional[str], tokens_in: int, tokens_out: int) -> float:
    try:
        model_prices = _PRICE_PER_1K.get(provider.lower()) or {}
        price_in, price_out = (0.0, 0.0)
        if model and model in model_prices:
            price_in, price_out = model_prices[model]
        return (max(0, tokens_in) / 1000.0) * price_in + (max(0, tokens_out) / 1000.0) * price_out
    except Exception:
        return 0.0


# ---------------- Helpers ----------------

def _iso_now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def hash_api_key_to_id(secret: Optional[str]) -> Optional[str]:
    if not secret:
        return None
    try:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()
    except Exception:
        return None


def record_api_event(event: ApiUsageEvent | Dict[str, Any]) -> None:
    """Adds event to in-memory buffer and updates session counters + metrics."""
    try:
        # Normalize to dataclass
        if not isinstance(event, ApiUsageEvent):
            # Ensure required fields exist; fill defaults
            e = ApiUsageEvent(
                ts_utc=str(event.get("ts_utc") or _iso_now_utc()),
                provider=str(event.get("provider") or "unknown").lower(),
                model=event.get("model"),
                api_key_hash=event.get("api_key_hash"),
                endpoint=event.get("endpoint"),
                req_count=int(event.get("req_count", 1) or 1),
                success=bool(event.get("success")),
                http_status=event.get("http_status"),
                latency_ms=event.get("latency_ms"),
                tokens_in=int(event.get("tokens_in", 0) or 0),
                tokens_out=int(event.get("tokens_out", 0) or 0),
                cost_usd=float(event.get("cost_usd", 0.0) or 0.0),
                error_code=event.get("error_code"),
                extra_json=event.get("extra_json"),
            )
        else:
            e = event

        key = (e.provider, e.model, e.api_key_hash)
        with _lock:
            _events_buffer.append(e)
            ctr = _session_counters.setdefault(key, {
                "req_count": 0.0,
                "success_count": 0.0,
                "tokens_in": 0.0,
                "tokens_out": 0.0,
                "cost_usd": 0.0,
                "latency_ms_sum": 0.0,
            })
            ctr["req_count"] += float(e.req_count)
            ctr["success_count"] += 1.0 if e.success else 0.0
            ctr["tokens_in"] += float(e.tokens_in)
            ctr["tokens_out"] += float(e.tokens_out)
            ctr["cost_usd"] += float(e.cost_usd)
            ctr["latency_ms_sum"] += float(e.latency_ms or 0)
    except Exception:
        # Do not let metrics path break main flows
        pass

    # Prometheus session metrics
    try:
        from metrics import (
            SESSION_API_REQUESTS_TOTAL,
            SESSION_API_TOKENS_IN_TOTAL,
            SESSION_API_TOKENS_OUT_TOTAL,
            SESSION_API_COST_USD_TOTAL,
            DAILY_API_REQUESTS_BY_KEY_TOTAL,
        )
        # Session counters
        SESSION_API_REQUESTS_TOTAL.labels(e.provider, e.model or "").inc(e.req_count)
        if e.tokens_in:
            SESSION_API_TOKENS_IN_TOTAL.labels(e.provider, e.model or "").inc(e.tokens_in)
        if e.tokens_out:
            SESSION_API_TOKENS_OUT_TOTAL.labels(e.provider, e.model or "").inc(e.tokens_out)
        if e.cost_usd:
            SESSION_API_COST_USD_TOTAL.labels(e.provider, e.model or "").inc(e.cost_usd)
        # Daily per-key gauges for today: we set current value after flushing, but for fast feedback update with +1 best-effort
        if e.api_key_hash:
            DAILY_API_REQUESTS_BY_KEY_TOTAL.labels(e.provider, e.model or "", (e.api_key_hash or "")[:8], "today").inc(e.req_count)
    except Exception:
        pass


def flush_api_events_to_db() -> int:
    """Flushes buffered events to SQLite in a single transaction, updates daily gauges.

    Returns number of events flushed.
    """
    drained: List[ApiUsageEvent] = []
    with _lock:
        if not _events_buffer:
            drained = []
        else:
            drained = list(_events_buffer)
            _events_buffer.clear()
    if not drained:
        return 0

    # Convert to plain dicts for DB layer
    payload: List[Dict[str, Any]] = [asdict(e) for e in drained]
    inserted = 0
    try:
        inserted = database.insert_api_usage_events(payload)
    except Exception:
        # If DB fails, requeue back to buffer to retry later (best-effort)
        with _lock:
            _events_buffer[0:0] = drained  # prepend back to preserve order
        return 0

    try:
        update_daily_metrics()
    except Exception:
        pass
    return inserted


def _today_utc_date_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _yesterday_utc_date_str() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def update_daily_metrics() -> None:
    """Reads DB aggregates for today/yesterday and updates daily_* gauges."""
    try:
        from metrics import DAILY_API_REQUESTS_TOTAL, DAILY_API_REQUESTS_BY_KEY_TOTAL
    except Exception:
        return

    # Today
    try:
        today = _today_utc_date_str()
        rows = database.get_api_usage_daily_for_day(today)
        # Reset all series we touch by setting to 0 first is tricky; Prometheus doesn't support delete.
        for r in rows:
            provider = r.get("provider") or ""
            model = r.get("model") or ""
            DAILY_API_REQUESTS_TOTAL.labels(provider, model, "today").set(float(r.get("req_count") or 0))
            # Per-key
            key = r.get("api_key_hash") or ""
            if key:
                DAILY_API_REQUESTS_BY_KEY_TOTAL.labels(provider, model, key[:8], "today").set(float(r.get("req_count") or 0))
    except Exception:
        pass

    # Yesterday
    try:
        yday = _yesterday_utc_date_str()
        rows = database.get_api_usage_daily_for_day(yday)
        for r in rows:
            provider = r.get("provider") or ""
            model = r.get("model") or ""
            DAILY_API_REQUESTS_TOTAL.labels(provider, model, "yesterday").set(float(r.get("req_count") or 0))
            key = r.get("api_key_hash") or ""
            if key:
                DAILY_API_REQUESTS_BY_KEY_TOTAL.labels(provider, model, key[:8], "yesterday").set(float(r.get("req_count") or 0))
    except Exception:
        pass


def init_session(session_id: Optional[str] = None, git_sha: Optional[str] = None, container_id: Optional[str] = None) -> None:
    """Initializes a logical bot session for persistence and metrics."""
    global _session_id, _session_started_at
    _session_id = session_id
    _session_started_at = datetime.now(timezone.utc)
    try:
        database.start_session(session_id or "default", git_sha=git_sha, container_id=container_id)
    except Exception:
        pass


def close_session() -> None:
    try:
        if _session_id:
            database.end_session(_session_id)
    except Exception:
        pass
