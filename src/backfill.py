import threading
import time
import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any, List

from . import config
from .database import (
    get_db_connection,
    upsert_raw_article,
    set_article_summary,
)
from .parser import get_articles_from_page, get_article_text

logger = logging.getLogger(__name__)


class _BackfillState:
    def __init__(self):
        # Shared state guarded by GIL; operations are simple
        self.collect_running: bool = False
        self.collect_until: datetime = config.BASE_AUTO_UPDATE_TARGET_DT
        self.collect_thread: Optional[threading.Thread] = None
        self.collect_last_page: int = 0
        self.collect_processed: int = 0
        self.collect_last_ts: Optional[str] = None
        self.collect_goal_pages: Optional[int] = None
        self.collect_goal_total: Optional[int] = None
        self.collect_scanning: bool = False
        self.collect_scan_page: int = 0

        self.sum_running: bool = False
        self.sum_until: datetime = config.BASE_AUTO_UPDATE_TARGET_DT
        self.sum_thread: Optional[threading.Thread] = None
        self.sum_processed: int = 0
        self.sum_last_article_id: Optional[int] = None
        self.sum_model: str = config.BASE_AUTO_SUM_MODEL
        self.sum_goal_total: Optional[int] = None

        self._stop_event_collect = threading.Event()
        self._stop_event_sum = threading.Event()

    def snapshot(self) -> Dict[str, Any]:
        # Compute progress percentages (best-effort)
        collect_progress_pct: int | None = None
        try:
            if self.collect_running and isinstance(self.collect_goal_total, int) and self.collect_goal_total > 0:
                collect_progress_pct = int(
                    max(0.0, min(100.0, (float(self.collect_processed) / float(self.collect_goal_total)) * 100.0))
                )
        except Exception:
            collect_progress_pct = None

        sum_progress_pct: int | None = None
        try:
            if self.sum_running and isinstance(self.sum_goal_total, int) and self.sum_goal_total > 0:
                sum_progress_pct = int(max(0.0, min(100.0, (float(self.sum_processed) / float(self.sum_goal_total)) * 100.0)))
        except Exception:
            sum_progress_pct = None

        # Period string (e.g., 24.08.2025-01.01.2025)
        try:
            from datetime import datetime as _dt
            _from = self.collect_until.strftime("%d.%m.%Y")
            _to = _dt.now(config.APP_TZ).strftime("%d.%m.%Y")
            collect_period = f"{_to}-{_from}"
        except Exception:
            collect_period = None

        return {
            "collect_running": self.collect_running,
            "collect_until": self.collect_until.isoformat(),
            "collect_last_page": self.collect_last_page,
            "collect_processed": self.collect_processed,
            "collect_last_ts": self.collect_last_ts,
            "collect_scanning": self.collect_scanning,
            "collect_scan_page": self.collect_scan_page,
            "collect_goal_pages": self.collect_goal_pages,
            "collect_goal_total": self.collect_goal_total,
            "collect_period": collect_period,
            "collect_progress_pct": collect_progress_pct,
            "sum_running": self.sum_running,
            "sum_until": self.sum_until.isoformat(),
            "sum_processed": self.sum_processed,
            "sum_last_article_id": self.sum_last_article_id,
            "sum_model": self.sum_model,
            "sum_goal_total": self.sum_goal_total,
            "sum_progress_pct": sum_progress_pct,
        }

    # --- Persistence helpers ---
    def persist(self) -> None:
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE backfill_progress
                    SET collect_running = ?,
                        collect_until = ?,
                        collect_scanning = ?,
                        collect_scan_page = ?,
                        collect_last_page = ?,
                        collect_processed = ?,
                        collect_last_ts = ?,
                        collect_goal_pages = ?,
                        collect_goal_total = ?,
                        sum_running = ?,
                        sum_until = ?,
                        sum_processed = ?,
                        sum_last_article_id = ?,
                        sum_model = ?,
                        sum_goal_total = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                    """,
                    (
                        1 if self.collect_running else 0,
                        self.collect_until.isoformat(),
                        1 if self.collect_scanning else 0,
                        int(self.collect_scan_page or 0),
                        int(self.collect_last_page or 0),
                        int(self.collect_processed or 0),
                        self.collect_last_ts,
                        int(self.collect_goal_pages or 0) if self.collect_goal_pages is not None else None,
                        int(self.collect_goal_total or 0) if self.collect_goal_total is not None else None,
                        1 if self.sum_running else 0,
                        self.sum_until.isoformat(),
                        int(self.sum_processed or 0),
                        int(self.sum_last_article_id or 0) if self.sum_last_article_id else None,
                        self.sum_model,
                        int(self.sum_goal_total or 0) if self.sum_goal_total is not None else None,
                    ),
                )
                conn.commit()
        except Exception:
            # Persistence is best-effort; avoid breaking workers
            pass

    def load(self) -> None:
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT * FROM backfill_progress WHERE id = 1")
                row = cur.fetchone()
                if row:
                    # Keep env-provided targets but restore counters for visibility
                    self.collect_last_page = int(row["collect_last_page"] or 0)
                    self.collect_processed = int(row["collect_processed"] or 0)
                    self.collect_last_ts = row["collect_last_ts"]
                    self.sum_processed = int(row["sum_processed"] or 0)
                    self.sum_last_article_id = int(row["sum_last_article_id"] or 0) or None
                    self.sum_model = row["sum_model"] or self.sum_model
                    try:
                        self.sum_goal_total = int(row["sum_goal_total"]) if row["sum_goal_total"] is not None else None
                    except Exception:
                        self.sum_goal_total = None
                    try:
                        self.collect_scanning = bool(int(row["collect_scanning"])) if row["collect_scanning"] is not None else False
                    except Exception:
                        self.collect_scanning = False
                    try:
                        self.collect_scan_page = int(row["collect_scan_page"]) if row["collect_scan_page"] is not None else 0
                    except Exception:
                        self.collect_scan_page = 0
                    try:
                        self.collect_goal_pages = int(row["collect_goal_pages"]) if row["collect_goal_pages"] is not None else None
                    except Exception:
                        self.collect_goal_pages = None
                    try:
                        self.collect_goal_total = int(row["collect_goal_total"]) if row["collect_goal_total"] is not None else None
                    except Exception:
                        self.collect_goal_total = None
        except Exception:
            pass


STATE = _BackfillState()
STATE.load()


# --- Helpers ---

def _iso(dt: datetime) -> str:
    # Persist in DB as text in ISO format "YYYY-MM-DD HH:MM:SS"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _should_stop_collect() -> bool:
    return STATE._stop_event_collect.is_set() or not STATE.collect_running


def _should_stop_sum() -> bool:
    return STATE._stop_event_sum.is_set() or not STATE.sum_running


# --- Collect worker ---

def _collect_loop():
    logger.debug("Backfill-Collect: started. Target <= %s", STATE.collect_until)
    try:
        # 0) One-time scan forward to determine goal pages and total items up to target
        if STATE.collect_scanning or STATE.collect_goal_total is None or STATE.collect_goal_pages is None:
            try:
                logger.info("Процесс сканирования периода начался (%s)", config.BASE_AUTO_UPDATE_PERIOD_STRING)
            except Exception:
                pass
            STATE.collect_scanning = True
            # keep existing scan_page if resuming
            STATE.persist()
            goal_pages = 0
            goal_total = 0
            scan_page = max(1, int(STATE.collect_scan_page or 0))
            while True:
                arts = get_articles_from_page(scan_page)
                if not arts:
                    break
                all_older = True
                for a in arts:
                    if a["published_at"] >= STATE.collect_until:
                        goal_total += 1
                        all_older = False
                goal_pages += 1
                STATE.collect_scan_page = scan_page
                # Persist incremental goal so bots/UI can show 0% bar immediately
                STATE.collect_goal_pages = goal_pages
                STATE.collect_goal_total = goal_total
                STATE.persist()
                if all_older:
                    break
                scan_page += 1
                time.sleep(0.05)
            # Final persist already done incrementally
            STATE.collect_scanning = False
            try:
                logger.info("Процесс сканирования периода завершен (%s)", config.BASE_AUTO_UPDATE_PERIOD_STRING)
            except Exception:
                pass
            STATE.persist()

        # 1) Main collection pass from last known page (resume), refetching the same page for idempotency
        if (STATE.collect_goal_total is not None and STATE.collect_goal_pages is not None) and not STATE.collect_scanning:
            try:
                logger.info("Сканирование периода уже выполнено (%s)", config.BASE_AUTO_UPDATE_PERIOD_STRING)
            except Exception:
                pass
        try:
            logger.info("Процесс обновления начался")
        except Exception:
            pass
        page = max(1, int(STATE.collect_last_page or 0))
        STATE.collect_last_page = 0
        while not _should_stop_collect():
            logger.debug("Backfill-Collect: fetching page %s", page)
            articles = get_articles_from_page(page)
            STATE.collect_last_page = page
            if not articles:
                logger.debug("Backfill-Collect: no articles on page %s, stopping.", page)
                break

            # Articles on the listing are ordered newest->older within the page.
            # Process top-to-bottom; stop condition when all items are older than target.
            reached_target_on_page = True
            page_added = 0
            for a in articles:
                published_at: datetime = a["published_at"]
                if published_at >= STATE.collect_until:
                    reached_target_on_page = False  # still at or after target boundary
                # Stop collecting beyond target only when strictly older than target
                if published_at < STATE.collect_until:
                    # Skip items older than target
                    continue

                url = a["link"]
                title = a["title"]
                # Try fetch full text for richer DB entry
                text = get_article_text(url) or ""
                # upsert to avoid duplicates; increment processed only when insert/update occurs
                before = STATE.collect_processed
                upsert_raw_article(url=url, title=title, published_at_iso=_iso(published_at), content=text)
                # We can't easily know if upsert inserted vs updated; still treat as progressed
                STATE.collect_processed = before + 1
                page_added += 1
                STATE.collect_last_ts = _iso(published_at)
                STATE.persist()
                if _should_stop_collect():
                    break
                time.sleep(0.1)

            if _should_stop_collect():
                break
            logger.debug(
                "Backfill-Collect: page %s done: +%s, total=%s, last_ts=%s",
                page,
                page_added,
                STATE.collect_processed,
                STATE.collect_last_ts,
            )
            STATE.persist()
            # If every item on this page was strictly older than target, we can stop
            if reached_target_on_page:
                logger.debug("Backfill-Collect: target boundary reached on page %s, stopping.", page)
                break
            page += 1
            time.sleep(0.5)
    except Exception as e:
        logger.exception("Backfill-Collect: crashed: %s", e)
    finally:
        STATE.collect_running = False
        STATE._stop_event_collect.clear()
        STATE.persist()
        logger.debug("Backfill-Collect: stopped. processed=%s last_page=%s", STATE.collect_processed, STATE.collect_last_page)


# --- Summarization worker ---

def _pick_candidates_for_summary(until_dt: datetime, limit: int = 10) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, url, title, content, published_at
            FROM articles
            WHERE published_at >= ?
              AND (summary_text IS NULL OR TRIM(summary_text) = '')
            ORDER BY published_at DESC
            LIMIT ?
            """,
            (_iso(until_dt), limit),
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]


def _count_summarization_goal(until_dt: datetime) -> int:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*) FROM articles
            WHERE published_at >= ?
              AND (summary_text IS NULL OR TRIM(summary_text) = '')
            """,
            (_iso(until_dt),),
        )
        row = cursor.fetchone()
        return int(row[0] if row and row[0] is not None else 0)


def _summarize_one(article: Dict[str, Any]) -> bool:
    # Respect requested model for auto-sum by adjusting summarizer module variable
    try:
        from . import summarizer as _summ
        model = (STATE.sum_model or "").strip().lower() or "gemini"
        _summ.LLM_PRIMARY = model
    except Exception:
        _summ = None  # type: ignore

    text: str = article.get("content") or ""
    if not text:
        # fetch on demand
        text = get_article_text(article["url"]) or ""
        if text:
            # persist fetched content for future use
            try:
                upsert_raw_article(url=article["url"], title=article.get("title") or "", published_at_iso=_iso(article["published_at"]), content=text)
            except Exception:
                pass
    if not text:
        return False

    summary: Optional[str] = None
    try:
        if _summ:
            summary = _summ.summarize_text_local(text)
    except Exception:
        summary = None
    if summary:
        set_article_summary(article_id=int(article["id"]), summary_text=summary)
        return True
    return False


def _sum_loop():
    logger.debug("Backfill-Summarize: started. Target <= %s model=%s", STATE.sum_until, STATE.sum_model)
    try:
        while not _should_stop_sum():
            batch = _pick_candidates_for_summary(STATE.sum_until, limit=5)
            if not batch:
                logger.debug("Backfill-Summarize: no candidates, stopping.")
                break
            succeeded = 0
            for art in batch:
                if _should_stop_sum():
                    break
                ok = _summarize_one(art)
                STATE.sum_last_article_id = int(art["id"])
                if ok:
                    STATE.sum_processed += 1
                    succeeded += 1
                time.sleep(0.1)
            STATE.persist()
            logger.debug(
                "Backfill-Summarize: batch done: +%s/%s ok, total=%s",
                succeeded,
                len(batch),
                STATE.sum_processed,
            )
            time.sleep(0.5)
    except Exception as e:
        logger.exception("Backfill-Summarize: crashed: %s", e)
    finally:
        STATE.sum_running = False
        STATE._stop_event_sum.clear()
        STATE.persist()
        logger.debug("Backfill-Summarize: stopped. processed=%s", STATE.sum_processed)


# --- Public API ---

def start_collect(until_dt: Optional[datetime] = None) -> None:
    if STATE.collect_running:
        return
    STATE.collect_until = until_dt or config.BASE_AUTO_UPDATE_TARGET_DT
    STATE._stop_event_collect.clear()
    STATE.collect_running = True
    logger.info("Процесс обновления начался")
    STATE.persist()
    t = threading.Thread(target=_collect_loop, name="backfill-collect", daemon=True)
    STATE.collect_thread = t
    t.start()


def stop_collect() -> None:
    STATE._stop_event_collect.set()
    STATE.collect_running = False
    logger.info("Процесс обновления завершен")
    STATE.persist()


def start_summarize(until_dt: Optional[datetime] = None, model: Optional[str] = None) -> None:
    if STATE.sum_running:
        return
    STATE.sum_until = until_dt or config.BASE_AUTO_UPDATE_TARGET_DT
    if model:
        STATE.sum_model = model.strip().lower()
    else:
        STATE.sum_model = config.BASE_AUTO_SUM_MODEL
    # Compute goal for progress bar
    try:
        STATE.sum_goal_total = _count_summarization_goal(STATE.sum_until)
    except Exception:
        STATE.sum_goal_total = None
    STATE.sum_processed = 0
    STATE._stop_event_sum.clear()
    STATE.sum_running = True
    logger.info("Процесс суммаризации начался")
    STATE.persist()
    t = threading.Thread(target=_sum_loop, name="backfill-summarize", daemon=True)
    STATE.sum_thread = t
    t.start()


def stop_summarize() -> None:
    STATE._stop_event_sum.set()
    STATE.sum_running = False
    logger.info("Процесс суммаризации завершен")
    STATE.persist()


def get_status() -> Dict[str, Any]:
    return STATE.snapshot()
