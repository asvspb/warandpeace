import os
import time
from datetime import datetime, timezone
from typing import Optional, Dict

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server  # type: ignore
except Exception:  # pragma: no cover - graceful fallback for test env
    class _NoopMetric:
        def __init__(self, *args, **kwargs):
            pass
        def inc(self, *args, **kwargs):
            return None
        def set(self, *args, **kwargs):
            return None
        def observe(self, *args, **kwargs):
            return None
        def labels(self, *args, **kwargs):
            return self

    # Fallback shims
    Counter = _NoopMetric  # type: ignore
    Gauge = _NoopMetric  # type: ignore
    Histogram = _NoopMetric  # type: ignore

    def start_http_server(*args, **kwargs):  # type: ignore
        return None


# Metrics definitions
ARTICLES_INGESTED = Counter(
    "articles_ingested_total", "Total number of raw articles ingested"
)
ARTICLES_POSTED = Counter(
    "articles_posted_total", "Total number of articles posted to Telegram"
)
ERRORS_TOTAL = Counter(
    "errors_total", "Total number of errors by type", labelnames=("type",)
)
JOB_DURATION = Histogram(
    "job_duration_seconds", "Duration of the scheduled job check_and_post_news"
)
LAST_ARTICLE_AGE_MIN = Gauge(
    "last_article_age_minutes", "Age (in minutes) of the last article in DB"
)
DLQ_SIZE = Gauge("dlq_size", "Number of items in the DLQ")

# --- Network/VPN metrics ---
VPN_ACTIVE = Gauge("vpn_active", "VPN active heuristic (0/1)")
DNS_RESOLVE_OK = Gauge(
    "dns_resolve_ok",
    "DNS resolution success (0/1) for important hosts",
    labelnames=("hostname",),
)
# Info-like gauge to attach network labels (value is always 1)
NETWORK_INFO = Gauge(
    "network_info",
    "Network context info as labels",
    labelnames=("default_iface", "egress_ip", "public_ip"),
)

# --- Session metrics ---
# Внешние HTTP-вызовы (к источникам, LLM-провайдерам и т.п.)
EXTERNAL_HTTP_REQUESTS_TOTAL = Counter(
    "external_http_requests_total",
    "Total number of outgoing HTTP requests",
    labelnames=("target", "method", "status_group"),  # target: rss|llm|tg|other; status_group: 2xx|4xx|5xx|timeout
)

EXTERNAL_HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "external_http_request_duration_seconds",
    "Outgoing HTTP request duration (seconds)",
    labelnames=("target",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# Статистика обработанных новостей за сессию
SESSION_ARTICLES_PROCESSED = Counter(
    "session_articles_processed_total", "Number of articles processed in current session"
)

# Токены LLM (разделяем prompt/completion для большей наглядности)
TOKENS_CONSUMED_PROMPT_TOTAL = Counter(
    "tokens_consumed_prompt_total", "Total prompt tokens consumed", labelnames=("provider", "model")
)
TOKENS_CONSUMED_COMPLETION_TOTAL = Counter(
    "tokens_consumed_completion_total", "Total completion tokens consumed", labelnames=("provider", "model")
)

# Per-key token counters (provider + key id)
TOKENS_CONSUMED_PROMPT_BY_KEY_TOTAL = Counter(
    "tokens_consumed_prompt_by_key_total",
    "Total prompt tokens consumed per API key",
    labelnames=("provider", "key_id"),
)
TOKENS_CONSUMED_COMPLETION_BY_KEY_TOTAL = Counter(
    "tokens_consumed_completion_by_key_total",
    "Total completion tokens consumed per API key",
    labelnames=("provider", "key_id"),
)

# Per-key request counter (how many LLM requests were made)
LLM_REQUESTS_BY_KEY_TOTAL = Counter(
    "llm_requests_by_key_total",
    "Total number of LLM requests per API key",
    labelnames=("provider", "key_id"),
)

# Время старта сессии (устанавливается один раз при загрузке приложения)
SESSION_START_TIME_SECONDS = Gauge(
    "session_start_time_seconds", "Process session start time in seconds since UNIX epoch"
)


def start_metrics_server() -> None:
    """Starts Prometheus metrics HTTP server if enabled by env."""
    enabled = os.getenv("METRICS_ENABLED", "true").lower() in {"1", "true", "yes"}
    if not enabled:
        return
    port = int(os.getenv("METRICS_PORT", "8000"))
    start_http_server(port)


def update_last_article_age(published_at_iso: Optional[str]) -> None:
    """Update LAST_ARTICLE_AGE_MIN gauge from ISO datetime string.

    Accepts both "YYYY-MM-DDTHH:MM:SS" and "YYYY-MM-DD HH:MM:SS".
    """
    if not published_at_iso:
        return
    iso = published_at_iso.replace(" ", "T")
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    age_min = (now - dt).total_seconds() / 60.0
    if age_min >= 0:
        LAST_ARTICLE_AGE_MIN.set(age_min)
