
import sqlite3
from typing import List, Dict, Any, Optional
from datetime import date, datetime, timedelta
import calendar as py_calendar
from src.database import get_db_connection, get_content_hash_groups, list_articles_by_content_hash, list_dlq_items
from prometheus_client import REGISTRY  # type: ignore
from prometheus_client.parser import text_string_to_metric_families  # type: ignore
import os
import time

def get_articles(page: int = 1, page_size: int = 50, q: Optional[str] = None, 
                 start_date: Optional[str] = None, end_date: Optional[str] = None, has_content: int = 1) -> (List[Dict[str, Any]], int):
    """Fetches a paginated list of articles with optional filters."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        base_query = "FROM articles WHERE 1=1"
        count_query = "SELECT COUNT(*) " + base_query
        select_query = "SELECT id, title, url, canonical_link, published_at " + base_query
        
        params = {}
        
        if q:
            select_query += " AND title LIKE :q"
            count_query += " AND title LIKE :q"
            params['q'] = f"%{q}%"
            
        if start_date:
            select_query += " AND published_at >= :start_date"
            count_query += " AND published_at >= :start_date"
            params['start_date'] = start_date

        if end_date:
            select_query += " AND published_at <= :end_date"
            count_query += " AND published_at <= :end_date"
            params['end_date'] = end_date

        if has_content == 1:
            select_query += " AND content IS NOT NULL AND content <> ''"
            count_query += " AND content IS NOT NULL AND content <> ''"

        # Get total count for pagination
        total_articles = cursor.execute(count_query, params).fetchone()[0]
        
        # Get paginated articles
        select_query += " ORDER BY published_at DESC LIMIT :limit OFFSET :offset"
        params['limit'] = page_size
        params['offset'] = (page - 1) * page_size
        
        articles = cursor.execute(select_query, params).fetchall()
        
        return [dict(row) for row in articles], total_articles

def get_article_by_id(article_id: int) -> Optional[Dict[str, Any]]:
    """Fetches a single article by its ID."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM articles WHERE id = ?", (article_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_dashboard_stats() -> Dict[str, Any]:
    """Fetches statistics for the main dashboard."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            stats: Dict[str, Any] = {}

            # Total articles
            cursor.execute("SELECT COUNT(*) FROM articles")
            stats['total_articles'] = cursor.fetchone()[0]

            # Last published article date
            cursor.execute("SELECT MAX(published_at) FROM articles")
            last_published = cursor.fetchone()[0]
            stats['last_published_date'] = last_published if last_published else "N/A"

            # DLQ count
            cursor.execute("SELECT COUNT(*) FROM dlq")
            stats['dlq_count'] = cursor.fetchone()[0]

            return stats
    except sqlite3.Error:
        # Graceful fallback when tables/database are not available
        return {'total_articles': 0, 'last_published_date': 'N/A', 'dlq_count': 0}

# --- Duplicates Services ---

def get_duplicate_groups() -> List[Dict[str, Any]]:
    """Reuses the database function to get duplicate groups."""
    return get_content_hash_groups(min_count=2)

def get_articles_by_hash(content_hash: str) -> List[Dict[str, Any]]:
    """Reuses the database function to get articles by a specific hash."""
    return list_articles_by_content_hash(content_hash)

# --- DLQ Services ---

def get_dlq_items(entity_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Reuses the database function to get DLQ items."""
    return list_dlq_items(entity_type=entity_type, limit=500)


# --- Calendar and Daily Services ---

def _to_iso_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _month_bounds(year: int, month: int) -> (str, str):
    month_start = date(year, month, 1)
    last_day = py_calendar.monthrange(year, month)[1]
    month_end = date(year, month, last_day)
    # Inclusive day bounds at 00:00:00 to 23:59:59
    start_iso = f"{_to_iso_date(month_start)} 00:00:00"
    end_iso = f"{_to_iso_date(month_end)} 23:59:59"
    return start_iso, end_iso


def get_month_calendar_data(year: int, month: int) -> Dict[str, Any]:
    """Builds a calendar data model for the given month.

    Returns a dict with keys:
    - year, month
    - weeks: List[{
        'days': List[{'date': 'YYYY-MM-DD', 'day': int, 'in_month': bool, 'total': int, 'summarized': int}],
        'total': int, 'summarized': int, 'all_summarized': bool
      }]
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            start_iso, end_iso = _month_bounds(year, month)

            # Aggregate counts per calendar day within the month
            cursor.execute(
                """
                SELECT date(published_at) AS d,
                       COUNT(*) AS total,
                       SUM(CASE WHEN summary_text IS NOT NULL AND TRIM(summary_text) <> '' THEN 1 ELSE 0 END) AS summarized
                FROM articles
                WHERE published_at BETWEEN ? AND ?
                GROUP BY date(published_at)
                """,
                (start_iso, end_iso),
            )
            rows = cursor.fetchall()
            per_day: Dict[str, Dict[str, int]] = {
                row[0]: {"total": int(row[1] or 0), "summarized": int(row[2] or 0)} for row in rows
            }

            cal = py_calendar.Calendar(firstweekday=0)  # Monday=0 in Python 3.12+, but here 0 is Monday in calendar? In calendar, 0=Monday.
            # To be explicit across versions: ensure Monday-first weeks
            cal = py_calendar.Calendar(firstweekday=0)

            weeks: List[Dict[str, Any]] = []
            for week in cal.monthdatescalendar(year, month):
                week_days: List[Dict[str, Any]] = []
                week_total = 0
                week_summarized = 0
                for day_date in week:
                    d_iso = _to_iso_date(day_date)
                    counts = per_day.get(d_iso, {"total": 0, "summarized": 0})
                    in_month = (day_date.month == month)
                    week_total += counts["total"]
                    week_summarized += counts["summarized"]
                    week_days.append({
                        "date": d_iso,
                        "day": day_date.day,
                        "in_month": in_month,
                        "total": counts["total"],
                        "summarized": counts["summarized"],
                    })
                all_summarized = week_total > 0 and (week_total == week_summarized)
                weeks.append({
                    "days": week_days,
                    "total": week_total,
                    "summarized": week_summarized,
                    "all_summarized": all_summarized,
                })

            return {
                "year": year,
                "month": month,
                "weeks": weeks,
            }
    except Exception:
        # Fallback for empty/missing DB or environment without write access
        today = date.today()
        cal = py_calendar.Calendar(firstweekday=0)
        weeks = []
        for week in cal.monthdatescalendar(year, month):
            week_days = [{"date": _to_iso_date(d), "day": d.day, "in_month": d.month == month, "total": 0, "summarized": 0} for d in week]
            weeks.append({"days": week_days, "total": 0, "summarized": 0, "all_summarized": False})
        return {"year": year, "month": month, "weeks": weeks}


def get_daily_articles(day_iso: str) -> List[Dict[str, Any]]:
    """Returns articles for a specific day (YYYY-MM-DD)."""
    try:
        # Validate date format
        datetime.strptime(day_iso, "%Y-%m-%d")
    except ValueError:
        return []

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, url, canonical_link, published_at, summary_text
            FROM articles
            WHERE date(published_at) = ?
            ORDER BY published_at DESC
            """,
            (day_iso,),
        )
        return [dict(row) for row in cursor.fetchall()]


# --- Session Stats (Prometheus-based) ---

def get_session_stats() -> Dict[str, Any]:
    """Aggregates selected session metrics from Prometheus default REGISTRY.

    Returns a dict with keys:
    - external_http_requests: int
    - articles_processed: int
    - tokens_prompt: int
    - tokens_completion: int
    - session_start: ISO8601 or None
    - uptime_seconds: int
    """
    stats: Dict[str, Any] = {
        "external_http_requests": 0,
        "articles_processed": 0,
        "tokens_prompt": 0,
        "tokens_completion": 0,
        # dynamic per-key breakdown: list of {provider, key_id, prompt, completion}
        "token_keys": [],
        "session_start": None,
        "uptime_seconds": 0,
    }

    try:
        def _iter_metrics():
            """Yield metric families either from remote scrape or local REGISTRY."""
            scrape_url = os.getenv("METRICS_SCRAPE_URL")
            if not scrape_url:
                port = os.getenv("METRICS_PORT", "8000").strip()
                # Assume bot exposes Prometheus on this port (start_metrics_server)
                scrape_url = f"http://127.0.0.1:{port}/"
            # Try remote scrape first
            try:
                import requests  # lazy import to avoid test env issues
                resp = requests.get(scrape_url.rstrip("/") + "/metrics", timeout=1.5)
                if resp.ok and resp.text:
                    for fam in text_string_to_metric_families(resp.text):
                        yield fam
                    return
            except Exception:
                # Fallback to local registry
                pass
            for fam in REGISTRY.collect():
                yield fam

        # Temporary aggregation for per-key
        per_key: Dict[tuple[str, str], Dict[str, int]] = {}
        families: Dict[str, Any] = {}
        import math
        def _safe_int(v: Any) -> int:
            try:
                f = float(v)
                if not math.isfinite(f):
                    return 0
                return int(f)
            except Exception:
                return 0

        for metric in _iter_metrics():
            name = getattr(metric, "name", "")
            families[name] = metric
            if name == "external_http_requests":
                # Sum over all label combinations
                stats["external_http_requests"] = int(sum(_safe_int(sample.value) for sample in metric.samples))
            elif name == "session_articles_processed":
                stats["articles_processed"] = int(sum(_safe_int(sample.value) for sample in metric.samples))
            elif name == "tokens_consumed_prompt":
                stats["tokens_prompt"] = int(sum(_safe_int(sample.value) for sample in metric.samples))
            elif name == "tokens_consumed_completion":
                stats["tokens_completion"] = int(sum(_safe_int(sample.value) for sample in metric.samples))
            # per-key aggregation handled after the loop
            elif name == "session_start_time_seconds":
                samples = list(metric.samples)
                if samples:
                    session_start = float(samples[-1].value)
                    # Match bot logs date format: "%d-%m.%y - [%H:%M]"
                    dt_local = datetime.fromtimestamp(session_start)
                    stats["session_start"] = dt_local.strftime("%d-%m.%y - [%H:%M]")
                    stats["uptime_seconds"] = int(max(0, time.time() - session_start))

        # Second pass: per-key metrics including request counts
        if families.get("tokens_consumed_prompt_by_key"):
            for sample in families["tokens_consumed_prompt_by_key"].samples:
                labels = getattr(sample, "labels", {}) or {}
                provider = labels.get("provider") or ""
                key_id = labels.get("key_id") or ""
                k = (provider, key_id)
                if provider and key_id:
                    bucket = per_key.setdefault(k, {"prompt": 0, "completion": 0, "requests": 0})
                    bucket["prompt"] += _safe_int(sample.value)
        if families.get("tokens_consumed_completion_by_key"):
            for sample in families["tokens_consumed_completion_by_key"].samples:
                labels = getattr(sample, "labels", {}) or {}
                provider = labels.get("provider") or ""
                key_id = labels.get("key_id") or ""
                k = (provider, key_id)
                if provider and key_id:
                    bucket = per_key.setdefault(k, {"prompt": 0, "completion": 0, "requests": 0})
                    bucket["completion"] += _safe_int(sample.value)
        # llm_requests_by_key_total counter is optional
        fam_req = families.get("llm_requests_by_key_total") or families.get("llm_requests_by_key")
        if fam_req:
            for sample in fam_req.samples:
                labels = getattr(sample, "labels", {}) or {}
                provider = labels.get("provider") or ""
                key_id = labels.get("key_id") or ""
                k = (provider, key_id)
                if provider and key_id:
                    bucket = per_key.setdefault(k, {"prompt": 0, "completion": 0, "requests": 0})
                    bucket["requests"] += _safe_int(sample.value)

        # Flatten per-key aggregation into a list and sort
        token_keys = []
        for (provider, key_id), vals in per_key.items():
            token_keys.append({
                "provider": provider,
                "key_id": key_id,
                "prompt": int(vals.get("prompt", 0)),
                "completion": int(vals.get("completion", 0)),
                "requests": int(vals.get("requests", 0)),
            })
        token_keys.sort(key=lambda x: (x["provider"], x["key_id"]))
        stats["token_keys"] = token_keys
    except Exception:
        # Be conservative; return what we have
        pass

    return stats
