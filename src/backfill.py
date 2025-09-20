import threading
import time
import logging
import os
import asyncio
from datetime import datetime, timedelta, date
from typing import Optional, Dict, Any, List

from . import config
from .database import (
    get_db_connection,
    upsert_raw_article,
    set_article_summary,
)
from .parser import get_articles_from_page, get_article_text
from .async_parser import fetch_articles_for_date
from .time_utils import to_utc

logger = logging.getLogger(__name__)

# Optional SSE broadcast for web UI updates
try:  # pragma: no cover
    from src.webapp.server import _sse_broadcast  # type: ignore
except Exception:  # pragma: no cover
    def _sse_broadcast(_obj: dict) -> None:  # type: ignore
        return None


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
        # Build period string (e.g., 24.08.2025-01.12.2024)
        try:
            from datetime import datetime as _dt
            _from = self.collect_until.strftime("%d.%m.%Y")
            _to = _dt.now(config.APP_TZ).strftime("%d.%m.%Y")
            collect_period = f"{_to}-{_from}"
        except Exception:
            collect_period = None

        # Day-based progress that accounts for already populated historical data
        # Compute lower UTC date corresponding to local midnight of collect_until
        days_total: int | None = None
        days_done: int | None = None
        try:
            lower_local_midnight = datetime(
                self.collect_until.year,
                self.collect_until.month,
                self.collect_until.day,
                0,
                0,
                0,
                tzinfo=self.collect_until.tzinfo or config.APP_TZ,
            )
            lower_utc_date = to_utc(lower_local_midnight, config.APP_TZ).date().isoformat()
        except Exception:
            try:
                lower_utc_date = self.collect_until.date().isoformat()
            except Exception:
                lower_utc_date = None  # give up

        # Query DB for distinct days filled since lower_utc_date
        if lower_utc_date:
            try:
                with get_db_connection() as conn:
                    cur = conn.cursor()
                    # days_done: number of distinct calendar days in DB between lower_utc_date and today (UTC)
                    cur.execute(
                        """
                        SELECT COUNT(DISTINCT CAST(published_at AS DATE))
                        FROM articles
                        WHERE CAST(published_at AS DATE) BETWEEN CAST(? AS DATE) AND CURRENT_DATE
                        """,
                        (lower_utc_date,),
                    )
                    row = cur.fetchone()
                    days_done = int(row[0] if row and row[0] is not None else 0)

                    # days_total: inclusive number of days from lower_utc_date to today
                    cur.execute(
                        """
                        SELECT (CURRENT_DATE - CAST(? AS DATE))::int + 1
                        """,
                        (lower_utc_date,),
                    )
                    row2 = cur.fetchone()
                    days_total = int(row2[0] if row2 and row2[0] is not None else 0)
            except Exception:
                days_total, days_done = None, None

        # Compute percentage based on days
        collect_progress_pct: int | None = None
        try:
            if isinstance(days_total, int) and days_total > 0 and isinstance(days_done, int):
                collect_progress_pct = int(
                    max(0.0, min(100.0, (float(days_done) / float(days_total)) * 100.0))
                )
        except Exception:
            collect_progress_pct = None

        # Summarization progress remains item-based
        sum_progress_pct: int | None = None
        try:
            if self.sum_running and isinstance(self.sum_goal_total, int) and self.sum_goal_total > 0:
                sum_progress_pct = int(
                    max(0.0, min(100.0, (float(self.sum_processed) / float(self.sum_goal_total)) * 100.0))
                )
        except Exception:
            sum_progress_pct = None

        # Expose day-based totals in existing fields for UI compatibility
        goal_pages = days_total if isinstance(days_total, int) else self.collect_goal_pages
        scan_page = days_done if isinstance(days_done, int) else self.collect_scan_page
        goal_total = days_total if isinstance(days_total, int) else self.collect_goal_total
        processed = days_done if isinstance(days_done, int) else self.collect_processed

        return {
            "collect_running": self.collect_running,
            "collect_until": self.collect_until.isoformat(),
            "collect_last_page": self.collect_last_page,
            "collect_processed": processed,
            "collect_last_ts": self.collect_last_ts,
            "collect_scanning": self.collect_scanning,
            "collect_scan_page": scan_page,
            "collect_goal_pages": goal_pages,
            "collect_goal_total": goal_total,
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
    """
    Дата‑ориентированный сбор: идём от сегодня к целевой дате STATE.collect_until (в прошлое),
    для каждого дня собираем пары (title, link) через архив и сохраняем контент.

    Это гарантирует покрытие календарных дней, в отличие от обхода ленты по страницам.
    """
    logger.debug("Backfill-Collect: started (date mode). Target <= %s", STATE.collect_until)
    try:
        # Определяем границы в локальной TZ приложения
        today_local: date = datetime.now(config.APP_TZ).date()
        try:
            lower_local: date = STATE.collect_until.astimezone(config.APP_TZ).date()
        except Exception:
            lower_local = STATE.collect_until.date()  # best‑effort

        if lower_local > today_local:
            logger.debug("Backfill-Collect: target is in the future; nothing to do.")
            return

        total_days = (today_local - lower_local).days + 1
        # Цели прогресса: страницами считаем «дни»
        STATE.collect_scanning = False
        STATE.collect_goal_pages = total_days
        STATE.collect_goal_total = 0  # будет обновляться по мере обнаружения статей
        STATE.collect_last_page = 0
        STATE.collect_scan_page = 0
        STATE.collect_processed = 0
        STATE.collect_last_ts = None
        STATE.persist()
        try:
            _sse_broadcast({"type": "backfill_updated"})
        except Exception:
            pass

        from concurrent.futures import ThreadPoolExecutor, as_completed

        for day_index in range(total_days):
            if _should_stop_collect():
                break
            target_day = today_local - timedelta(days=day_index)
            try:
                logger.info("Сбор статей за %s...", target_day.isoformat())
            except Exception:
                pass

            # Рассчитываем UTC-день, в который попадает локальная полночь target_day
            dt_local_midnight = datetime.combine(target_day, datetime.min.time())
            try:
                utc_dt = to_utc(dt_local_midnight, config.APP_TZ)
                db_day_iso = utc_dt.date().isoformat()
            except Exception:
                utc_dt = dt_local_midnight
                db_day_iso = target_day.isoformat()

            # Оптимизация: если за этот UTC-день уже есть записи — пропускаем сетевые запросы
            try:
                with get_db_connection() as _conn:
                    _cur = _conn.cursor()
                    _cur.execute("SELECT 1 FROM articles WHERE date(published_at) = ? LIMIT 1", (db_day_iso,))
                    _row = _cur.fetchone()
                    if _row:
                        STATE.collect_scan_page = day_index + 1
                        STATE.collect_last_page = day_index + 1
                        STATE.persist()
                        try:
                            _sse_broadcast({"type": "backfill_updated"})
                        except Exception:
                            pass
                        try:
                            logger.debug("Пропуск %s: уже заполнено для UTC-дня %s", target_day.isoformat(), db_day_iso)
                        except Exception:
                            pass
                        # Пейсинг между днями и далее
                        try:
                            time.sleep(max(0.0, float(config.BACKFILL_SLEEP_PAGE_MS) / 1000.0))
                        except Exception:
                            pass
                        continue
            except Exception:
                # Если запрос к БД не удался — никак не оптимизируем, продолжаем обычный сбор
                pass

            # Получаем список ссылок за конкретный день (архивом для скорости и полноты)
            try:
                pairs: List[tuple[str, str]] = asyncio.run(
                    fetch_articles_for_date(target_day, archive_only=True)
                )
            except Exception:
                pairs = []

            STATE.collect_goal_total = int(STATE.collect_goal_total or 0) + len(pairs)
            STATE.collect_scan_page = day_index + 1
            STATE.collect_last_page = day_index + 1
            STATE.persist()
            try:
                _sse_broadcast({"type": "backfill_updated"})
            except Exception:
                pass

            if not pairs:
                # Ничего не нашли за день — двигаемся дальше
                try:
                    time.sleep(0.05)
                except Exception:
                    pass
                continue

            # Подготовим timestamp публикации (UTC ISO) как «начало суток» для этого дня
            try:
                published_at_utc_iso = utc_dt.isoformat()
            except Exception:
                # Фолбэк: локальный ISO без TZ
                published_at_utc_iso = _iso(dt_local_midnight)

            def _process_pair(pair: tuple[str, str]) -> bool:
                title, link = pair
                text = get_article_text(link) or ""
                if not text:
                    return False
                upsert_raw_article(url=link, title=title, published_at_iso=published_at_utc_iso, content=text)
                return True

            added_today = 0
            with ThreadPoolExecutor(max_workers=config.BACKFILL_CONCURRENCY) as executor:
                futures = [executor.submit(_process_pair, p) for p in pairs]
                for fut in as_completed(futures):
                    try:
                        if fut.result():
                            STATE.collect_processed += 1
                            added_today += 1
                            STATE.collect_last_ts = _iso(datetime.now(config.APP_TZ))
                            STATE.persist()
                    except Exception:
                        pass

            logger.debug(
                "Backfill-Collect: %s done: +%s, total=%s",
                target_day.isoformat(),
                added_today,
                STATE.collect_processed,
            )
            STATE.persist()
            try:
                _sse_broadcast({"type": "backfill_updated"})
            except Exception:
                pass

            # Пейсинг между днями
            try:
                time.sleep(max(0.0, float(config.BACKFILL_SLEEP_PAGE_MS) / 1000.0))
            except Exception:
                pass
    except Exception as e:
        logger.exception("Backfill-Collect: crashed: %s", e)
    finally:
        STATE.collect_running = False
        STATE._stop_event_collect.clear()
        STATE.persist()
        logger.debug(
            "Backfill-Collect: stopped. processed=%s last_page=%s",
            STATE.collect_processed,
            STATE.collect_last_page,
        )


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
