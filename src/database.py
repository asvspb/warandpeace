import sqlite3
import hashlib
from contextlib import contextmanager
import logging
import os
import shutil
from datetime import datetime
from typing import Optional, Dict, Any, List

# Support both package and module execution contexts
try:  # When imported as part of the 'src' package (e.g., uvicorn src.webapp.server:app)
    from . import config  # type: ignore
except Exception:  # When running scripts like 'python src/bot.py'
    import config  # type: ignore

DATABASE_NAME = config.DB_SQLITE_PATH
logger = logging.getLogger()

@contextmanager
def get_db_connection():
    """Контекстный менеджер для соединения с БД.

    Гарантирует существование директории БД и безопасно закрывает соединение.
    """
    conn = None
    try:
        db_dir = os.path.dirname(DATABASE_NAME)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        conn = sqlite3.connect(DATABASE_NAME)
        conn.row_factory = sqlite3.Row
        yield conn
    except sqlite3.Error as e:
        logger.error(f"Database connection error: {e}")
        raise
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass

def init_db():
    """
    Инициализирует или обновляет схему базы данных.
    - Добавляет таблицу 'articles' со всеми необходимыми полями, включая 'backfill_status'.
    - Выполняет миграцию данных из старой схемы, если это необходимо.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 1. Проверяем текущие колонки
        cursor.execute("PRAGMA table_info(articles)")
        columns = [column['name'] for column in cursor.fetchall()]

        # 2. Если таблицы нет или схема старая — создаём новую схему с каноническими полями
        need_recreate = not columns or any(col not in columns for col in [
            'url', 'title', 'published_at', 'summary_text', 'created_at', 'backfill_status'
        ])

        if need_recreate:
            logger.info("Миграция схемы 'articles' до новой версии (canonical_link, content, индексы)...")

            # Пытаемся сделать резервную копию файла БД перед сложной миграцией
            try:
                _ = backup_database_copy()
            except Exception:
                pass

            # Транзакция для миграции
            cursor.execute("BEGIN")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS articles_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    canonical_link TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    published_at TIMESTAMP NOT NULL,
                    content TEXT,
                    content_hash TEXT,
                    summary_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    backfill_status TEXT CHECK(backfill_status IN ('success', 'failed', 'skipped'))
                )
                """
            )

            # Перенос совместимых данных из старой таблицы, если она была
            if columns:
                try:
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO articles_new (id, url, canonical_link, title, published_at, summary_text, created_at, updated_at, backfill_status)
                        SELECT id, url, url, title, published_at, summary_text, created_at, CURRENT_TIMESTAMP, backfill_status FROM articles
                        """
                    )
                    cursor.execute("DROP TABLE articles")
                except sqlite3.OperationalError:
                    logger.info("Старая таблица 'articles' отсутствует, создаём с нуля")
            cursor.execute("ALTER TABLE articles_new RENAME TO articles")
            conn.commit()
        else:
            # Лёгкая миграция: добавляем недостающие колонки для старой схемы
            missing_columns = set([
                'canonical_link', 'content', 'content_hash', 'updated_at'
            ]) - set(columns)

            if missing_columns:
                # Резервная копия перед изменением структуры
                try:
                    _ = backup_database_copy()
                except Exception:
                    pass

                cursor.execute("BEGIN")

                if 'canonical_link' in missing_columns:
                    cursor.execute("ALTER TABLE articles ADD COLUMN canonical_link TEXT")
                    # Заполняем canonical_link из url для уже существующих записей
                    try:
                        cursor.execute(
                            "UPDATE articles SET canonical_link = url WHERE canonical_link IS NULL OR TRIM(canonical_link) = ''"
                        )
                    except sqlite3.OperationalError:
                        pass

                if 'content' in missing_columns:
                    cursor.execute("ALTER TABLE articles ADD COLUMN content TEXT")

                if 'content_hash' in missing_columns:
                    cursor.execute("ALTER TABLE articles ADD COLUMN content_hash TEXT")

                if 'updated_at' in missing_columns:
                    # В SQLite нельзя добавлять колонку с неконстантным DEFAULT через ALTER TABLE
                    cursor.execute("ALTER TABLE articles ADD COLUMN updated_at TIMESTAMP")
                    try:
                        cursor.execute("UPDATE articles SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
                    except sqlite3.OperationalError:
                        pass
                conn.commit()

        # 3. Индексы
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles (published_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_backfill_status ON articles (backfill_status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_content_hash ON articles (content_hash)")

        # 4. Создаем таблицу DLQ (если нет)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS dlq (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_ref TEXT NOT NULL,
                error_code TEXT,
                error_payload TEXT,
                attempts INTEGER DEFAULT 1,
                first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_dlq_entity ON dlq (entity_type, entity_ref)"
        )

        # 5. Создаем таблицу для дайджестов (без изменений)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 6. Создаем таблицу для отложенных публикаций
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_publications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                published_at TIMESTAMP NOT NULL,
                summary_text TEXT NOT NULL,
                attempts INTEGER DEFAULT 0,
                last_error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pending_publications_created_at ON pending_publications (created_at)")
        
        # 7. Таблица для WebAuthn-учётных данных администратора
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS webauthn_credential (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT NOT NULL,
              credential_id BLOB NOT NULL UNIQUE,
              public_key BLOB NOT NULL,
              sign_count INTEGER NOT NULL DEFAULT 0,
              transports TEXT,
              aaguid TEXT,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              last_used_at TIMESTAMP
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_webauthn_user ON webauthn_credential (user_id)")
        
        # --- API usage persistence schema (ensure) ---
        try:
            ensure_api_usage_schema(cursor)
        except Exception as e:
            logger.error(f"Не удалось инициализировать схему метрик API: {e}")

        # --- Session stats daily persistence schema (ensure) ---
        try:
            ensure_session_stats_schema(cursor)
        except Exception as e:
            logger.error(f"Не удалось инициализировать схему session_stats: {e}")

        logger.info("Инициализация базы данных завершена.")

        # 8. Таблица прогресса бэкфилла (для мониторинга и возобновления)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS backfill_progress (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                collect_running INTEGER DEFAULT 0,
                collect_until TEXT,
                collect_scanning INTEGER DEFAULT 0,
                collect_scan_page INTEGER DEFAULT 0,
                collect_last_page INTEGER DEFAULT 0,
                collect_processed INTEGER DEFAULT 0,
                collect_last_ts TEXT,
                collect_goal_pages INTEGER,
                collect_goal_total INTEGER,
                sum_running INTEGER DEFAULT 0,
                sum_until TEXT,
                sum_processed INTEGER DEFAULT 0,
                sum_last_article_id INTEGER,
                sum_model TEXT,
                sum_goal_total INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Ensure single row exists
        cursor.execute("INSERT OR IGNORE INTO backfill_progress (id) VALUES (1)")
        # Backward-compatible: add missing columns if table existed earlier
        try:
            cursor.execute("ALTER TABLE backfill_progress ADD COLUMN sum_goal_total INTEGER")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE backfill_progress ADD COLUMN collect_scanning INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE backfill_progress ADD COLUMN collect_scan_page INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE backfill_progress ADD COLUMN collect_goal_pages INTEGER")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE backfill_progress ADD COLUMN collect_goal_total INTEGER")
        except Exception:
            pass
        conn.commit()


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
            cursor.execute(
                "INSERT INTO articles (url, canonical_link, title, published_at, summary_text) VALUES (?, ?, ?, ?, ?)",
                (url, canonical_link, title, published_at_iso, summary)
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            # Это не ошибка, а ожидаемое поведение, если статья уже есть
            return None
        except sqlite3.Error as e:
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

def ensure_api_usage_schema(cursor: Optional[sqlite3.Cursor] = None) -> None:
    """Создает таблицы и индексы для персистентной статистики API-использования.

    Может принимать внешний курсор (для вызова из init_db), либо создаёт свой.
    """
    def _exec(cur: sqlite3.Cursor, sql: str, params: tuple = ()) -> None:
        cur.execute(sql, params)

    if cursor is None:
        with get_db_connection() as conn:
            cur = conn.cursor()
            _ensure_api_usage_schema_inner(cur)
            conn.commit()
        return
    _ensure_api_usage_schema_inner(cursor)


def _ensure_api_usage_schema_inner(cur: sqlite3.Cursor) -> None:
    # 1) Сырые события
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS api_usage_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
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
          cost_usd REAL DEFAULT 0.0,
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

    # 2) Дневные агрегаты
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
          cost_usd_total REAL NOT NULL DEFAULT 0.0,
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
        cur.execute(
            """
            INSERT OR REPLACE INTO sessions (session_id, started_at_utc, git_sha, container_id, notes)
            VALUES (?, COALESCE((SELECT started_at_utc FROM sessions WHERE session_id = ?), ?), ?, ?, ?)
            """,
            (session_id, session_id, ts, git_sha, container_id, notes),
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

def ensure_session_stats_schema(cursor: Optional[sqlite3.Cursor] = None) -> None:
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


def _ensure_session_stats_schema_inner(cur: sqlite3.Cursor) -> None:
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
    # Ensure single state row exists
    cur.execute("INSERT OR IGNORE INTO session_stats_state (id) VALUES (1)")


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
    """Возвращает число статей с датой публикации day_utc (UTC), по префиксу строки."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT COUNT(*) FROM articles WHERE substr(published_at, 1, 10) = ?",
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
        except sqlite3.Error as e:
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


def backup_database_copy() -> Optional[str]:
    """Делает файловую резервную копию SQLite-BD рядом с исходником.

    Возвращает путь к бэкапу или None, если файла БД ещё нет.
    Не выбрасывает исключения наружу — логирует и возвращает None.
    """
    try:
        if not os.path.exists(DATABASE_NAME):
            return None
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        backup_path = f"{DATABASE_NAME}.bak-{timestamp}"
        os.makedirs(os.path.dirname(backup_path) or ".", exist_ok=True)
        shutil.copy2(DATABASE_NAME, backup_path)
        logger.info(f"Создан бэкап БД: {backup_path}")
        return backup_path
    except Exception as e:
        logger.warning(f"Не удалось создать бэкап БД: {e}")
        return None


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
            "SELECT content FROM digests WHERE created_at >= datetime('now', '-' || ? || ' days') ORDER BY created_at DESC",
            (days,)
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
            WHERE published_at >= datetime('now', '-' || ? || ' days')
              AND content IS NOT NULL AND TRIM(content) <> ''
            ORDER BY published_at DESC
            LIMIT ?
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
        except sqlite3.IntegrityError:
            logger.warning(f"Статья '{title}' уже находится в очереди на публикацию.")
        except sqlite3.Error as e:
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
