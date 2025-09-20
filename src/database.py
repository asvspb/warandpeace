import hashlib
from contextlib import contextmanager
import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any, List, Sequence, Iterator
import re

# Support both package and module execution contexts
try:  # When imported as part of the 'src' package (e.g., uvicorn src.webapp.server:app)
    from . import config  # type: ignore
except Exception:  # When running scripts like 'python src/bot.py'
    import config  # type: ignore

# SQLAlchemy Postgres support
try:
    from .db.engine import create_engine_from_env  # type: ignore
except Exception:
    from db.engine import create_engine_from_env  # type: ignore

logger = logging.getLogger()


class _RowAdapter:
    """Адаптер строки результата SQLAlchemy для совместимости со sqlite3.Row.

    Поддерживает row['col'] и row[0], а также dict(row).
    """
    __slots__ = ("_keys", "_mapping", "_values")

    def __init__(self, keys: Sequence[str], row: Any):  # type: ignore
        # SQLAlchemy Row имеет ._mapping и .keys()
        try:
            self._mapping = row._mapping  # type: ignore
            self._keys = list(keys)
            self._values = [self._mapping.get(k) for k in self._keys]
        except Exception:
            # fallback на dict(row)
            d = dict(row)
            self._keys = list(d.keys())
            self._values = [d[k] for k in self._keys]
            class _M(dict):
                def get(self, k, default=None):
                    return dict.__getitem__(self, k)
            self._mapping = _M(d)

    def __getitem__(self, key):  # type: ignore
        if isinstance(key, int):
            return self._values[key]
        return self._mapping[key]

    def items(self):  # type: ignore
        for k in self._keys:
            yield (k, self._mapping.get(k))

    def __iter__(self) -> Iterator[Any]:  # type: ignore
        # Позволяет dict(row) корректно собирать словарь
        return iter(self.items())


class _PgCursorAdapter:
    def __init__(self, sa_conn):
        from sqlalchemy import text as sa_text  # lazy import
        self._conn = sa_conn
        self._sa_text = sa_text
        self._last_result = None
        self.lastrowid: Optional[int] = None

    @staticmethod
    def _convert_qmarks(sql: str, params: Sequence[Any]) -> (str, Dict[str, Any]):  # type: ignore
        # Заменяет ? на :p0, :p1 ... и формирует словарь параметров
        idx = 0
        def repl(_):
            nonlocal idx
            name = f"p{idx}"
            idx += 1
            return f":{name}"
        new_sql = re.sub(r"\?", repl, sql)
        bind = {f"p{i}": params[i] for i in range(len(params))}
        return new_sql, bind

    def execute(self, sql: str, params: Optional[Sequence[Any]] = None):  # type: ignore
        self.lastrowid = None
        # Accept either positional (list/tuple) or named (dict) parameters
        if params is None:
            bind = {}
            new_sql = sql
        elif isinstance(params, dict):
            bind = params  # pass through named binds like :limit, :offset
            new_sql = sql
        else:
            new_sql, bind = self._convert_qmarks(sql, list(params))
        self._last_result = self._conn.execute(self._sa_text(new_sql), bind)
        # Спец-случай: нужно вернуть id вставленной статьи как lastrowid
        try:
            if sql.strip().lower().startswith("insert into articles"):
                # canonical_link — второй параметр в обоих INSERT
                if not isinstance(params, dict) and params is not None and len(params) >= 2:
                    canon = params[1]
                    row = self._conn.execute(self._sa_text("SELECT id FROM articles WHERE canonical_link = :canon LIMIT 1"), {"canon": canon}).fetchone()
                    if row is not None:
                        self.lastrowid = int(row[0])
        except Exception:
            pass
        return self

    def executemany(self, sql: str, seq_of_params: Sequence[Sequence[Any]]):  # type: ignore
        self.lastrowid = None
        if not seq_of_params:
            return self
        first = seq_of_params[0]
        if isinstance(first, dict):
            new_sql = sql
            rows = list(seq_of_params)  # already list of dicts
        else:
            # Преобразуем SQL один раз
            new_sql, _ = self._convert_qmarks(sql, list(first))
            rows = []
            for params in seq_of_params:
                _, bind = self._convert_qmarks(sql, list(params))
                rows.append(bind)
        self._last_result = self._conn.execute(self._sa_text(new_sql), rows)
        return self

    def fetchall(self):  # type: ignore
        if self._last_result is None:
            return []
        keys = list(self._last_result.keys())
        return [_RowAdapter(keys, r) for r in self._last_result.fetchall()]

    def fetchone(self):  # type: ignore
        if self._last_result is None:
            return None
        row = self._last_result.fetchone()
        if row is None:
            return None
        keys = list(self._last_result.keys())
        return _RowAdapter(keys, row)


class _PgConnectionAdapter:
    def __init__(self, sa_engine):
        self._engine = sa_engine
        self._conn = sa_engine
        self._trans = None
        try:
            self._trans = self._conn.begin()
        except Exception:
            self._trans = None

    def cursor(self):  # type: ignore
        return _PgCursorAdapter(self._conn)

    def commit(self):  # type: ignore
        try:
            if self._trans and self._trans.is_active:
                self._trans.commit()
                self._trans = self._conn.begin()
        except Exception:
            pass

    def close(self):  # type: ignore
        try:
            if self._trans and self._trans.is_active:
                self._trans.commit()
        except Exception:
            pass
        try:
            self._conn.close()
        except Exception:
            pass


@contextmanager
def get_db_connection():
    """Контекстный менеджер для соединения с БД (PostgreSQL only)."""
    sa_conn = None
    try:
        sa_conn = create_engine_from_env().connect()
        adapter = _PgConnectionAdapter(sa_conn)
        yield adapter
    except Exception as e:
        logger.error(f"Database connection error (PG): {e}")
        raise
    finally:
        try:
            if adapter:  # type: ignore
                adapter.close()  # type: ignore
        except Exception:
            pass

def init_db():
    """
    Инициализирует или обновляет схему базы данных (PostgreSQL-only).
    """
    try:
        try:
            from .db.schema import create_all_schema  # type: ignore
        except Exception:
            from db.schema import create_all_schema  # type: ignore
        engine = create_engine_from_env()
        create_all_schema(engine)
        logger.info("PG schema ensured via SQLAlchemy.")
        return
    except Exception as e:
        logger.error(f"Не удалось создать схему PG через SQLAlchemy: {e}")
        raise


def get_articles_for_backfill(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Получает статьи для обработки.

    Args:
        status: Если 'failed', возвращает только статьи с ошибками.
                Если None, возвращает статьи, которые еще не обрабатывались.

    Returns:
        Список словарей со статьями.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if status == 'failed':
            query = "SELECT * FROM articles WHERE backfill_status = 'failed' ORDER BY published_at DESC"
            cursor.execute(query)
        else:
            query = "SELECT * FROM articles WHERE backfill_status IS NULL ORDER BY published_at DESC"
            cursor.execute(query)
        
        articles = cursor.fetchall()
        return [dict(row) for row in articles]

def update_article_backfill_status(article_id: int, status: str, summary: Optional[str] = None):
    """
    Обновляет статус backfill для статьи и ее резюме, если применимо.

    Args:
        article_id: ID статьи для обновления.
        status: Новый статус ('success', 'failed', 'skipped').
        summary: Текст резюме, если статус 'success'.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if status == 'success' and summary:
            cursor.execute(
                "UPDATE articles SET backfill_status = ?, summary_text = ? WHERE id = ?",
                (status, summary, article_id)
            )
        else:
            cursor.execute(
                "UPDATE articles SET backfill_status = ? WHERE id = ?",
                (status, article_id)
            )
        conn.commit()
        logger.info(f"Статус статьи {article_id} обновлен на '{status}'.")

def add_article(url: str, title: str, published_at_iso: str, summary: str) -> Optional[int]:
    """
    Добавляет опубликованную статью в базу данных.
    Возвращает ID статьи, если она была добавлена, иначе None.
    """
    with get_db_connection() as conn:
        try:
            cursor = conn.cursor()
            # При добавлении поста сохраняем канонический URL; content может быть NULL в режиме «публикаций»
            try:
                from .url_utils import canonicalize_url  # локальный импорт, чтобы избежать циклов
            except Exception:
                def canonicalize_url(u: str) -> str:
                    return u

            canonical_link = canonicalize_url(url)
            # В PG используем UPSERT с возвратом id для нового ряда
            cursor.execute(
                """
                INSERT INTO articles (url, canonical_link, title, published_at, summary_text)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (canonical_link) DO NOTHING
                RETURNING id
                """,
                (url, canonical_link, title, published_at_iso, summary),
            )
            row = cursor.fetchone()
            if not row:
                return None
            conn.commit()
            return int(row[0])
        except Exception as e:
            logger.error(f"Ошибка при добавлении статьи {url}: {e}")
            return None

def is_article_posted(url: str) -> bool:
    """Проверяет, была ли статья уже опубликована (существует ли в БД)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            from .url_utils import canonicalize_url
        except Exception:
            def canonicalize_url(u: str) -> str:
                return u
        canonical_link = canonicalize_url(url)
        cursor.execute("SELECT 1 FROM articles WHERE canonical_link = ?", (canonical_link,))
        return cursor.fetchone() is not None


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# -------------------- API USAGE PERSISTENCE --------------------

def ensure_api_usage_schema(cursor: Optional[Any] = None) -> None:
    """Создает таблицы и индексы для персистентной статистики API-использования.

    Может принимать внешний курсор (для вызова из init_db), либо создаёт свой.
    """
    def _exec(cur, sql: str, params: tuple = ()) -> None:
        cur.execute(sql, params)

    if cursor is None:
        with get_db_connection() as conn:
            cur = conn.cursor()
            _ensure_api_usage_schema_inner(cur)
            conn.commit()
        return
    _ensure_api_usage_schema_inner(cursor)


def _ensure_api_usage_schema_inner(cur) -> None:
    # 1) Сырые события (PostgreSQL)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS api_usage_events (
          id BIGSERIAL PRIMARY KEY,
          ts_utc TEXT NOT NULL,
          provider TEXT NOT NULL,
          model TEXT,
          api_key_hash TEXT,
          endpoint TEXT,
          req_count INTEGER NOT NULL DEFAULT 1,
          success INTEGER NOT NULL,
          http_status INTEGER,
          latency_ms INTEGER,
          tokens_in INTEGER DEFAULT 0,
          tokens_out INTEGER DEFAULT 0,
          cost_usd DOUBLE PRECISION DEFAULT 0.0,
          error_code TEXT,
          extra_json TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_events_ts ON api_usage_events (ts_utc)")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_api_usage_events_provider_model ON api_usage_events (provider, model)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_api_usage_events_api_key_hash ON api_usage_events (api_key_hash)"
    )

    # 2) Дневные агрегаты (PostgreSQL)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS api_usage_daily (
          day_utc TEXT NOT NULL,
          provider TEXT NOT NULL,
          model TEXT,
          api_key_hash TEXT,
          req_count INTEGER NOT NULL DEFAULT 0,
          success_count INTEGER NOT NULL DEFAULT 0,
          tokens_in_total INTEGER NOT NULL DEFAULT 0,
          tokens_out_total INTEGER NOT NULL DEFAULT 0,
          cost_usd_total DOUBLE PRECISION NOT NULL DEFAULT 0.0,
          latency_ms_sum INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY (day_utc, provider, model, api_key_hash)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_daily_provider ON api_usage_daily (provider)")

    # 3) Сессии процесса бота (опционально)
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
          session_id TEXT PRIMARY KEY,
          started_at_utc TEXT NOT NULL,
          ended_at_utc TEXT,
          git_sha TEXT,
          container_id TEXT,
          notes TEXT
        )
        """
    )


def start_session(session_id: str, git_sha: Optional[str] = None, container_id: Optional[str] = None, notes: Optional[str] = None) -> None:
    """Регистрирует старт сессии процесса бота в БД."""
    from datetime import datetime, timezone

    with get_db_connection() as conn:
        cur = conn.cursor()
        ensure_api_usage_schema(cur)
        ts = datetime.now(timezone.utc).isoformat()
        # В PG обновляем только метаданные, стартовую метку не трогаем
        cur.execute(
            """
            INSERT INTO sessions (session_id, started_at_utc, git_sha, container_id, notes)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (session_id) DO UPDATE SET
              git_sha = EXCLUDED.git_sha,
              container_id = EXCLUDED.container_id,
              notes = EXCLUDED.notes
            """,
            (session_id, ts, git_sha, container_id, notes),
        )
        conn.commit()


def end_session(session_id: str) -> None:
    """Отмечает завершение сессии."""
    from datetime import datetime, timezone

    with get_db_connection() as conn:
        cur = conn.cursor()
        ensure_api_usage_schema(cur)
        ts = datetime.now(timezone.utc).isoformat()
        cur.execute(
            "UPDATE sessions SET ended_at_utc = ? WHERE session_id = ?",
            (ts, session_id),
        )
        conn.commit()


def upsert_api_usage_daily(
    day_utc: str,
    provider: str,
    model: Optional[str],
    api_key_hash: Optional[str],
    deltas: Dict[str, Any],
) -> None:
    """Инкрементально обновляет дневной агрегат по ключу (day, provider, model, key)."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        ensure_api_usage_schema(cur)
        cur.execute(
            """
            INSERT INTO api_usage_daily (
              day_utc, provider, model, api_key_hash,
              req_count, success_count, tokens_in_total, tokens_out_total,
              cost_usd_total, latency_ms_sum
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(day_utc, provider, model, api_key_hash) DO UPDATE SET
              req_count = req_count + excluded.req_count,
              success_count = success_count + excluded.success_count,
              tokens_in_total = tokens_in_total + excluded.tokens_in_total,
              tokens_out_total = tokens_out_total + excluded.tokens_out_total,
              cost_usd_total = cost_usd_total + excluded.cost_usd_total,
              latency_ms_sum = latency_ms_sum + excluded.latency_ms_sum
            """,
            (
                day_utc,
                provider,
                model,
                api_key_hash,
                int(deltas.get("req_count", 0) or 0),
                int(deltas.get("success_count", 0) or 0),
                int(deltas.get("tokens_in_total", 0) or 0),
                int(deltas.get("tokens_out_total", 0) or 0),
                float(deltas.get("cost_usd_total", 0.0) or 0.0),
                int(deltas.get("latency_ms_sum", 0) or 0),
            ),
        )
        conn.commit()


def insert_api_usage_events(batch: List[Dict[str, Any]]) -> int:
    """Вставляет батч событий в api_usage_events и инкрементит дневные агрегаты.

    Возвращает число вставленных событий.
    """
    if not batch:
        return 0
    from datetime import datetime, timezone

    def _to_day_utc(ts_utc: str) -> str:
        # Ожидаем ISO 8601, берём первые 10 символов (YYYY-MM-DD)
        if not ts_utc:
            return datetime.now(timezone.utc).date().isoformat()
        return (ts_utc[:10] if len(ts_utc) >= 10 else ts_utc)

    with get_db_connection() as conn:
        cur = conn.cursor()
        ensure_api_usage_schema(cur)
        cur.execute("BEGIN")

        # 1) Bulk insert raw events
        insert_sql = (
            """
            INSERT INTO api_usage_events (
              ts_utc, provider, model, api_key_hash, endpoint, req_count, success, http_status,
              latency_ms, tokens_in, tokens_out, cost_usd, error_code, extra_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
        )
        rows = []
        for e in batch:
            rows.append(
                (
                    e.get("ts_utc"),
                    e.get("provider"),
                    e.get("model"),
                    e.get("api_key_hash"),
                    e.get("endpoint"),
                    int(e.get("req_count", 1) or 1),
                    1 if (e.get("success") in (True, 1, "1")) else 0,
                    e.get("http_status"),
                    e.get("latency_ms"),
                    int(e.get("tokens_in", 0) or 0),
                    int(e.get("tokens_out", 0) or 0),
                    float(e.get("cost_usd", 0.0) or 0.0),
                    e.get("error_code"),
                    e.get("extra_json"),
                )
            )
        cur.executemany(insert_sql, rows)

        # 2) Aggregate deltas for daily upsert
        agg: Dict[tuple, Dict[str, Any]] = {}
        for e in batch:
            day = _to_day_utc(e.get("ts_utc"))
            key = (day, e.get("provider"), e.get("model"), e.get("api_key_hash"))
            a = agg.setdefault(
                key,
                {
                    "req_count": 0,
                    "success_count": 0,
                    "tokens_in_total": 0,
                    "tokens_out_total": 0,
                    "cost_usd_total": 0.0,
                    "latency_ms_sum": 0,
                },
            )
            a["req_count"] += int(e.get("req_count", 1) or 1)
            a["success_count"] += 1 if (e.get("success") in (True, 1, "1")) else 0
            a["tokens_in_total"] += int(e.get("tokens_in", 0) or 0)
            a["tokens_out_total"] += int(e.get("tokens_out", 0) or 0)
            a["cost_usd_total"] += float(e.get("cost_usd", 0.0) or 0.0)
            a["latency_ms_sum"] += int(e.get("latency_ms", 0) or 0)

        upsert_sql = (
            """
            INSERT INTO api_usage_daily (
              day_utc, provider, model, api_key_hash,
              req_count, success_count, tokens_in_total, tokens_out_total, cost_usd_total, latency_ms_sum
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(day_utc, provider, model, api_key_hash) DO UPDATE SET
              req_count = req_count + excluded.req_count,
              success_count = success_count + excluded.success_count,
              tokens_in_total = tokens_in_total + excluded.tokens_in_total,
              tokens_out_total = tokens_out_total + excluded.tokens_out_total,
              cost_usd_total = cost_usd_total + excluded.cost_usd_total,
              latency_ms_sum = latency_ms_sum + excluded.latency_ms_sum
            """
        )
        up_rows = []
        for (day, provider, model, api_key_hash), a in agg.items():
            up_rows.append(
                (
                    day,
                    provider,
                    model,
                    api_key_hash,
                    int(a.get("req_count", 0) or 0),
                    int(a.get("success_count", 0) or 0),
                    int(a.get("tokens_in_total", 0) or 0),
                    int(a.get("tokens_out_total", 0) or 0),
                    float(a.get("cost_usd_total", 0.0) or 0.0),
                    int(a.get("latency_ms_sum", 0) or 0),
                )
            )
        if up_rows:
            cur.executemany(upsert_sql, up_rows)

        conn.commit()
        return len(batch)


def recalc_api_usage_daily_for_range(from_date: str, to_date: str) -> None:
    """Идемпотентно пересчитывает агрегаты api_usage_daily за диапазон дат [from..to].

    Формат дат: YYYY-MM-DD (UTC).
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        ensure_api_usage_schema(cur)
        cur.execute("BEGIN")
        # Удаляем существующие агрегаты за диапазон
        cur.execute(
            "DELETE FROM api_usage_daily WHERE day_utc BETWEEN ? AND ?",
            (from_date, to_date),
        )
        # Считаем из сырья и вставляем
        cur.execute(
            """
            SELECT substr(ts_utc, 1, 10) AS day_utc,
                   provider,
                   model,
                   api_key_hash,
                   SUM(req_count) AS req_count,
                   SUM(CASE WHEN success IN (1, '1') THEN 1 ELSE 0 END) AS success_count,
                   SUM(tokens_in) AS tokens_in_total,
                   SUM(tokens_out) AS tokens_out_total,
                   SUM(cost_usd) AS cost_usd_total,
                   SUM(COALESCE(latency_ms, 0)) AS latency_ms_sum
            FROM api_usage_events
            WHERE substr(ts_utc, 1, 10) BETWEEN ? AND ?
            GROUP BY day_utc, provider, model, api_key_hash
            """,
            (from_date, to_date),
        )
        rows = cur.fetchall()
        insert_sql = (
            """
            INSERT INTO api_usage_daily (
              day_utc, provider, model, api_key_hash,
              req_count, success_count, tokens_in_total, tokens_out_total, cost_usd_total, latency_ms_sum
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
        )
        cur.executemany(insert_sql, [tuple(r) for r in rows])
        conn.commit()


def get_api_usage_daily_for_day(day_utc: str, provider: Optional[str] = None, model: Optional[str] = None) -> List[Dict[str, Any]]:
    """Возвращает список агрегатов за указанный день с фильтрами."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        q = (
            "SELECT provider, model, api_key_hash, req_count, success_count, tokens_in_total, tokens_out_total, cost_usd_total, latency_ms_sum "
            "FROM api_usage_daily WHERE day_utc = ?"
        )
        params: List[Any] = [day_utc]
        if provider:
            q += " AND provider = ?"
            params.append(provider)
        if model:
            q += " AND model = ?"
            params.append(model)
        q += " ORDER BY provider, model, COALESCE(api_key_hash, '')"
        cur.execute(q, tuple(params))
        return [dict(r) for r in cur.fetchall()]


def get_api_usage_daily_range(
    from_date: str,
    to_date: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Возвращает агрегаты по дням за диапазон дат."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        q = (
            "SELECT day_utc, provider, model, api_key_hash, req_count, success_count, tokens_in_total, tokens_out_total, cost_usd_total, latency_ms_sum "
            "FROM api_usage_daily WHERE day_utc BETWEEN ? AND ?"
        )
        params: List[Any] = [from_date, to_date]
        if provider:
            q += " AND provider = ?"
            params.append(provider)
        if model:
            q += " AND model = ?"
            params.append(model)
        q += " ORDER BY day_utc, provider, model"
        cur.execute(q, tuple(params))
        return [dict(r) for r in cur.fetchall()]


def prune_api_usage_old_events(ttl_days: int = 30) -> Dict[str, int]:
    """Удаляет сырьё и агрегаты старше TTL. Возвращает счётчики удалённых строк.

    Агрегаты удаляются только если есть соответствующее сырьё старше TTL или по дате day_utc < today-ttl.
    """
    from datetime import datetime, timedelta, timezone

    today = datetime.now(timezone.utc).date()
    cutoff_day = (today - timedelta(days=max(0, int(ttl_days)))).isoformat()
    removed_events = removed_daily = 0
    with get_db_connection() as conn:
        cur = conn.cursor()
        ensure_api_usage_schema(cur)
        cur.execute("BEGIN")
        # Remove raw events older than cutoff
        cur.execute("SELECT COUNT(*) FROM api_usage_events WHERE substr(ts_utc,1,10) < ?", (cutoff_day,))
        row = cur.fetchone()
        removed_events = int(row[0] or 0)
        cur.execute("DELETE FROM api_usage_events WHERE substr(ts_utc,1,10) < ?", (cutoff_day,))
        # Remove daily aggregates strictly older than cutoff
        cur.execute("SELECT COUNT(*) FROM api_usage_daily WHERE day_utc < ?", (cutoff_day,))
        row = cur.fetchone()
        removed_daily = int(row[0] or 0)
        cur.execute("DELETE FROM api_usage_daily WHERE day_utc < ?", (cutoff_day,))
        conn.commit()
    return {"events": removed_events, "daily": removed_daily}


# -------------------- SESSION STATS (DAILY) PERSISTENCE --------------------

def ensure_session_stats_schema(cursor: Optional[Any] = None) -> None:
    """Создает таблицы для посуточной статистики UI и состояние курсора.

    Таблицы:
      - session_stats_daily(day_utc, http_requests_total, articles_processed_total, tokens_in_total, tokens_out_total, updated_at)
      - session_stats_state(id=1, last_session_start REAL, last_http_counter INTEGER)
    """
    if cursor is None:
        with get_db_connection() as conn:
            cur = conn.cursor()
            _ensure_session_stats_schema_inner(cur)
            conn.commit()
        return
    _ensure_session_stats_schema_inner(cursor)


def _ensure_session_stats_schema_inner(cur) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS session_stats_daily (
          day_utc TEXT PRIMARY KEY,
          http_requests_total INTEGER NOT NULL DEFAULT 0,
          articles_processed_total INTEGER NOT NULL DEFAULT 0,
          tokens_in_total INTEGER NOT NULL DEFAULT 0,
          tokens_out_total INTEGER NOT NULL DEFAULT 0,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS session_stats_state (
          id INTEGER PRIMARY KEY CHECK(id = 1),
          last_session_start REAL,
          last_http_counter INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    # Ensure single state row exists (PostgreSQL)
    cur.execute("INSERT INTO session_stats_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING")


def get_session_stats_state() -> Dict[str, Any]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        ensure_session_stats_schema(cur)
        cur.execute("SELECT last_session_start, last_http_counter FROM session_stats_state WHERE id=1")
        row = cur.fetchone()
        if not row:
            return {"last_session_start": None, "last_http_counter": 0}
        return {"last_session_start": row[0], "last_http_counter": int(row[1] or 0)}


def update_session_stats_state(last_session_start: Optional[float], last_http_counter: int) -> None:
    with get_db_connection() as conn:
        cur = conn.cursor()
        ensure_session_stats_schema(cur)
        cur.execute(
            "UPDATE session_stats_state SET last_session_start = ?, last_http_counter = ? WHERE id = 1",
            (last_session_start, int(last_http_counter or 0)),
        )
        conn.commit()


def upsert_session_stats_daily(
    day_utc: str,
    http_requests_total: int,
    articles_processed_total: int,
    tokens_in_total: int,
    tokens_out_total: int,
) -> None:
    """Устанавливает агрегированные значения за день (идемпотентно)."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        ensure_session_stats_schema(cur)
        cur.execute(
            """
            INSERT INTO session_stats_daily (
              day_utc, http_requests_total, articles_processed_total, tokens_in_total, tokens_out_total
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(day_utc) DO UPDATE SET
              http_requests_total = excluded.http_requests_total,
              articles_processed_total = excluded.articles_processed_total,
              tokens_in_total = excluded.tokens_in_total,
              tokens_out_total = excluded.tokens_out_total,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                day_utc,
                int(http_requests_total or 0),
                int(articles_processed_total or 0),
                int(tokens_in_total or 0),
                int(tokens_out_total or 0),
            ),
        )
        conn.commit()


def get_session_stats_daily_for_day(day_utc: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        ensure_session_stats_schema(cur)
        cur.execute(
            "SELECT day_utc, http_requests_total, articles_processed_total, tokens_in_total, tokens_out_total, updated_at FROM session_stats_daily WHERE day_utc = ?",
            (day_utc,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "day_utc": row[0],
            "http_requests_total": int(row[1] or 0),
            "articles_processed_total": int(row[2] or 0),
            "tokens_in_total": int(row[3] or 0),
            "tokens_out_total": int(row[4] or 0),
            "updated_at": row[5],
        }


def get_session_stats_daily_range(from_date: str, to_date: str) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        ensure_session_stats_schema(cur)
        cur.execute(
            """
            SELECT day_utc, http_requests_total, articles_processed_total, tokens_in_total, tokens_out_total, updated_at
            FROM session_stats_daily
            WHERE day_utc BETWEEN ? AND ?
            ORDER BY day_utc ASC
            """,
            (from_date, to_date),
        )
        rows = cur.fetchall()
        return [
            {
                "day_utc": r[0],
                "http_requests_total": int(r[1] or 0),
                "articles_processed_total": int(r[2] or 0),
                "tokens_in_total": int(r[3] or 0),
                "tokens_out_total": int(r[4] or 0),
                "updated_at": r[5],
            }
            for r in rows
        ]


def count_articles_for_day(day_utc: str) -> int:
    """Возвращает число статей с датой публикации day_utc (UTC)."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT COUNT(*) FROM articles WHERE published_at::date = ?",
                (day_utc,),
            )
            row = cur.fetchone()
            return int(row[0] or 0) if row else 0
        except Exception:
            return 0


def upsert_raw_article(url: str, title: str, published_at_iso: str, content: str) -> Optional[int]:
    """Вставляет или обновляет «сырую» статью по canonical_link.

    Возвращает id статьи.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            try:
                from .url_utils import canonicalize_url
            except Exception:
                def canonicalize_url(u: str) -> str:  # type: ignore
                    return u

            canonical_link = canonicalize_url(url)
            content_hash = _sha256(content) if content else None

            # Проверяем существование
            cursor.execute(
                "SELECT id FROM articles WHERE canonical_link = ?",
                (canonical_link,)
            )
            row = cursor.fetchone()

            if row:
                article_id = row[0]
                cursor.execute(
                    """
                    UPDATE articles
                    SET url = ?, title = ?, published_at = ?, content = ?, content_hash = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (url, title, published_at_iso, content, content_hash, article_id)
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO articles (url, canonical_link, title, published_at, content, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (url, canonical_link, title, published_at_iso, content, content_hash)
                )
                article_id = cursor.lastrowid

            conn.commit()
            return article_id
        except Exception as e:
            logger.error(f"Ошибка upsert_raw_article для {url}: {e}")
            return None


def list_articles_without_summary_in_range(start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, content, published_at
            FROM articles
            WHERE (summary_text IS NULL OR TRIM(summary_text) = '')
              AND published_at BETWEEN ? AND ?
            ORDER BY published_at ASC
            """,
            (start_iso, end_iso),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]




def set_article_summary(article_id: int, summary_text: str) -> None:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE articles SET summary_text = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (summary_text, article_id),
        )
        conn.commit()


def dlq_record(entity_type: str, entity_ref: str, error_code: str = None, error_payload: str = None) -> None:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Пытаемся обновить attempts, если запись уже есть
        cursor.execute(
            "SELECT id, attempts FROM dlq WHERE entity_type = ? AND entity_ref = ?",
            (entity_type, entity_ref),
        )
        row = cursor.fetchone()
        if row:
            cursor.execute(
                """
                UPDATE dlq
                SET error_code = ?, error_payload = ?, attempts = attempts + 1, last_seen_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (error_code, error_payload, row[0]),
            )
        else:
            cursor.execute(
                """
                INSERT INTO dlq (entity_type, entity_ref, error_code, error_payload)
                VALUES (?, ?, ?, ?)
                """,
                (entity_type, entity_ref, error_code, error_payload),
            )
        conn.commit()


def get_dlq_size() -> int:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM dlq")
        row = cursor.fetchone()
        return int(row[0]) if row else 0


def list_dlq_items(entity_type: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    """Возвращает элементы DLQ с необязательной фильтрацией по типу.

    Args:
        entity_type: 'article' | 'summary' | None
        limit: максимальное число записей

    Returns:
        Список словарей с полями dlq.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if entity_type:
            cursor.execute(
                """
                SELECT id, entity_type, entity_ref, error_code, error_payload, attempts, first_seen_at, last_seen_at
                FROM dlq
                WHERE entity_type = ?
                ORDER BY last_seen_at DESC
                LIMIT ?
                """,
                (entity_type, limit),
            )
        else:
            cursor.execute(
                """
                SELECT id, entity_type, entity_ref, error_code, error_payload, attempts, first_seen_at, last_seen_at
                FROM dlq
                ORDER BY last_seen_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        return [dict(row) for row in cursor.fetchall()]


def delete_dlq_item(item_id: int) -> None:
    """Удаляет запись из DLQ по id."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM dlq WHERE id = ?", (item_id,))
        conn.commit()


def get_content_hash_groups(min_count: int = 2) -> List[Dict[str, Any]]:
    """Возвращает группы дубликатов по content_hash с количеством записей."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT content_hash AS hash, COUNT(*) AS cnt
            FROM articles
            WHERE content_hash IS NOT NULL AND TRIM(content_hash) <> ''
            GROUP BY content_hash
            HAVING COUNT(*) >= ?
            ORDER BY cnt DESC
            """,
            (min_count,),
        )
        return [dict(row) for row in cursor.fetchall()]


def list_articles_by_content_hash(content_hash: str) -> List[Dict[str, Any]]:
    """Список статей для заданного content_hash (для отчётов по дубликатам)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, canonical_link, published_at
            FROM articles
            WHERE content_hash = ?
            ORDER BY published_at DESC
            """,
            (content_hash,),
        )
        return [dict(row) for row in cursor.fetchall()]

def get_summaries_for_date_range(start_date: str, end_date: str) -> List[str]:
    """
    Извлекает тексты резюме статей за указанный диапазон дат.
    Даты должны быть в формате ISO 'YYYY-MM-DD HH:MM:SS'.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT summary_text 
            FROM articles
            WHERE summary_text IS NOT NULL
              AND published_at BETWEEN ? AND ?
            ORDER BY published_at DESC
        """, (start_date, end_date))
        return [item['summary_text'] for item in cursor.fetchall()]

def add_digest(period: str, content: str):
    """Сохраняет новый дайджест."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO digests (period, content) VALUES (?, ?)",
            (period, content)
        )
        conn.commit()

def get_digests_for_period(days: int) -> List[str]:
    """Извлекает дайджесты за последние `days` дней."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT content FROM digests
            WHERE created_at >= NOW() - (:p0::int) * INTERVAL '1 day'
            ORDER BY created_at DESC
            """,
            (days,),
        )
        return [item['content'] for item in cursor.fetchall()]

def get_stats() -> Dict[str, Any]:
    """Возвращает подробную статистику по статьям в базе."""
    stats: Dict[str, Any] = {
        'total_articles': 0,
        'success': 0,
        'failed': 0,
        'skipped': 0,
        'pending': 0, # Статьи, у которых статус IS NULL
        'last_posted_article': {
            'title': "Нет",
            'published_at': "Нет"
        }
    }
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # 1. Общее количество статей
        cursor.execute("SELECT COUNT(*) FROM articles")
        total = cursor.fetchone()
        if total:
            stats['total_articles'] = total[0]

        # 2. Статистика по статусам
        # Заменяем NULL на 'pending' для удобства подсчета
        query = "SELECT COALESCE(backfill_status, 'pending') as status, COUNT(*) as count FROM articles GROUP BY status"
        cursor.execute(query)
        status_counts = cursor.fetchall()
        for row in status_counts:
            if row['status'] in stats:
                stats[row['status']] = row['count']

        # 3. Последняя опубликованная статья
        cursor.execute("SELECT title, published_at FROM articles ORDER BY published_at DESC LIMIT 1")
        last_article_row = cursor.fetchone()
        
        if last_article_row:
            stats['last_posted_article'] = {
                "title": last_article_row['title'],
                "published_at": last_article_row['published_at']
            }
            
    return stats


def list_recent_articles(days: int = 7, limit: int = 200) -> List[Dict[str, Any]]:
    """Возвращает последние статьи за N дней (для анализа почти-дубликатов)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, title, canonical_link, content, published_at
            FROM articles
            WHERE published_at >= NOW() - (:p0::int) * INTERVAL '1 day'
              AND content IS NOT NULL AND TRIM(content) <> ''
            ORDER BY published_at DESC
            LIMIT :p1
            """,
            (days, limit),
        )
        return [dict(row) for row in cursor.fetchall()]


def get_last_posted_article() -> Optional[Dict[str, Any]]:
    """Возвращает самую последнюю опубликованную статью (по published_at)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, url, title, published_at, content, summary_text
            FROM articles
            ORDER BY published_at DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        return dict(row) if row else None


# --- Функции для очереди публикаций ---

def enqueue_publication(url: str, title: str, published_at: str, summary_text: str):
    """Добавляет статью в очередь на публикацию."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO pending_publications (url, title, published_at, summary_text, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (url, title, published_at, summary_text)
            )
            conn.commit()
            logger.info(f"Статья '{title}' добавлена в очередь на публикацию.")
        except Exception as e:
            msg = str(e).lower()
            if "unique" in msg or "duplicate" in msg:
                logger.warning(f"Статья '{title}' уже находится в очереди на публикацию.")
            else:
                logger.error(f"Ошибка при добавлении статьи '{title}' в очередь: {e}")

def dequeue_batch(limit: int = 5) -> List[Dict[str, Any]]:
    """Извлекает из очереди старейшие записи для отправки."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM pending_publications ORDER BY created_at ASC LIMIT ?",
            (limit,)
        )
        return [dict(row) for row in cursor.fetchall()]

def delete_sent_publication(publication_id: int):
    """Удаляет успешно отправленную публикацию из очереди."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM pending_publications WHERE id = ?", (publication_id,))
        conn.commit()

def increment_attempt_count(publication_id: int, last_error: str):
    """Увеличивает счетчик попыток и записывает последнюю ошибку."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE pending_publications
            SET attempts = attempts + 1, last_error = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (last_error, publication_id)
        )
        conn.commit()

def update_publication_summary(publication_id: int, summary_text: str):
    """Обновляет резюме для публикации в очереди."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE pending_publications
            SET summary_text = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (summary_text, publication_id)
        )
        conn.commit()
        logger.info(f"Резюме обновлено для публикации ID={publication_id} в очереди.")
