import os
import time
from datetime import datetime, timezone
from typing import Optional, Dict

try:
    from prometheus_client import Counter, Gauge, Histogram, start_http_server, REGISTRY
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
    REGISTRY = None # type: ignore

    def start_http_server(*args, **kwargs):  # type: ignore
        return None

# --- Idempotent Metric Registration ---
def _get_or_create_metric(metric_class, name, documentation, labelnames=()):
    """
    Gets an existing metric from the registry or creates a new one.
    This prevents 'Duplicated timeseries' errors during test collection.
    """
    if REGISTRY and name in REGISTRY._names_to_collectors:
        return REGISTRY._names_to_collectors[name]
    
    # If labelnames is an empty tuple, don't pass it to the constructor
    if labelnames:
        return metric_class(name, documentation, labelnames)
    else:
        return metric_class(name, documentation)

# --- Metrics definitions ---
ARTICLES_INGESTED = _get_or_create_metric(
    Counter,
    "articles_ingested_total", "Total number of raw articles ingested"
)
ARTICLES_POSTED = _get_or_create_metric(
    Counter,
    "articles_posted_total", "Total number of articles posted to Telegram"
)
ERRORS_TOTAL = _get_or_create_metric(
    Counter,
    "errors_total", "Total number of errors by type", labelnames=("type",)
)
JOB_DURATION = _get_or_create_metric(
    Histogram,
    "job_duration_seconds", "Duration of the scheduled job check_and_post_news"
)
LAST_ARTICLE_AGE_MIN = _get_or_create_metric(
    Gauge,
    "last_article_age_minutes", "Age (in minutes) of the last article in DB"
)
DLQ_SIZE = _get_or_create_metric(Gauge, "dlq_size", "Number of items in the DLQ")

# --- LLM Metrics ---
LLM_REQUESTS_TOTAL = _get_or_create_metric(
    Counter,
    "llm_requests_total",
    "Total number of requests to LLM providers",
    labelnames=("provider", "status", "reason"),
)
LLM_FALLBACKS_TOTAL = _get_or_create_metric(
    Counter,
    "llm_fallbacks_total",
    "Total number of fallbacks from one LLM provider to another",
    labelnames=("from_provider", "to_provider", "reason"),
)
LLM_LATENCY_SECONDS = _get_or_create_metric(
    Histogram,
    "llm_latency_seconds",
    "Latency of LLM provider requests",
    labelnames=("provider", "model"),
)
TELEGRAM_SEND_SECONDS = _get_or_create_metric(
    Histogram,
    "telegram_send_seconds",
    "Latency of sending messages to Telegram",
)

# --- Network/VPN metrics ---
VPN_ACTIVE = _get_or_create_metric(Gauge, "vpn_active", "VPN active heuristic (0/1)")
DNS_RESOLVE_OK = _get_or_create_metric(
    Gauge,
    "dns_resolve_ok",
    "DNS resolution success (0/1) for important hosts",
    labelnames=("hostname",),
)
# Info-like gauge to attach network labels (value is always 1)
NETWORK_INFO = _get_or_create_metric(
    Gauge,
    "network_info",
    "Network context info as labels",
    labelnames=("default_iface", "egress_ip", "public_ip"),
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
