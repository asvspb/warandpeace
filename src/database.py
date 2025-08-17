import sqlite3
import hashlib
from contextlib import contextmanager
import logging
import os
import shutil
from datetime import datetime
from typing import Optional, Dict, Any, List
from zoneinfo import ZoneInfo

# --- Safe import for URL canonicalization ---
try:
    # When running as a package (e.g. tests with pythonpath), this works
    from src.url_utils import canonicalize_url as _canonicalize_url  # type: ignore
except Exception:
    try:
        # When running as top-level module (python src/bot.py), import sibling
        from url_utils import canonicalize_url as _canonicalize_url  # type: ignore
    except Exception:
        def _canonicalize_url(u: str) -> str:  # type: ignore
            return u

# Support both package and module execution contexts
try:  # When imported as part of the 'src' package (e.g., uvicorn src.webapp.server:app)
    from . import config  # type: ignore
except Exception:  # When running scripts like 'python src/bot.py'
    import config  # type: ignore

DATABASE_NAME = config.DB_SQLITE_PATH
logger = logging.getLogger(__name__)
APP_TZ = ZoneInfo(os.getenv("TIMEZONE", "Europe/Moscow"))

@contextmanager
def get_db_connection():
    """Контекстный менеджер для соединения с БД."""
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
        if conn:
            conn.close()

def init_db():
    """Инициализирует или обновляет схему базы данных."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(articles)")
        columns = [column['name'] for column in cursor.fetchall()]

        need_recreate = not columns or any(col not in columns for col in [
            'url', 'title', 'published_at', 'summary_text', 'created_at', 'backfill_status'
        ])

        if need_recreate:
            logger.info("Миграция схемы 'articles' до новой версии...")
            backup_database_copy()
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
                    pass
            cursor.execute("ALTER TABLE articles_new RENAME TO articles")
            conn.commit()
        else:
            missing_columns = set(['canonical_link', 'content', 'content_hash', 'updated_at']) - set(columns)
            if missing_columns:
                backup_database_copy()
                cursor.execute("BEGIN")
                for col in missing_columns:
                    cursor.execute(f"ALTER TABLE articles ADD COLUMN {col} TEXT")
                conn.commit()

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles (published_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_backfill_status ON articles (backfill_status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_content_hash ON articles (content_hash)")

        # Остальные таблицы
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

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
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
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_pending_publications_created_at ON pending_publications (created_at)"
        )

        logger.info("Инициализация базы данных завершена.")

def get_articles_for_backfill(status: Optional[str] = None) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if status == 'failed':
            cursor.execute("SELECT * FROM articles WHERE backfill_status = 'failed' ORDER BY published_at DESC")
        else:
            cursor.execute("SELECT * FROM articles WHERE backfill_status IS NULL ORDER BY published_at DESC")
        return [dict(row) for row in cursor.fetchall()]

def update_article_backfill_status(article_id: int, status: str, summary: Optional[str] = None):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if status == 'success' and summary:
            cursor.execute("UPDATE articles SET backfill_status = ?, summary_text = ? WHERE id = ?", (status, summary, article_id))
        else:
            cursor.execute("UPDATE articles SET backfill_status = ? WHERE id = ?", (status, article_id))
        conn.commit()

def add_article(url: str, title: str, published_at_iso: str, summary: str) -> Optional[int]:
    with get_db_connection() as conn:
        try:
            canonical_link = _canonicalize_url(url)
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO articles (url, canonical_link, title, published_at, summary_text) VALUES (?, ?, ?, ?, ?)",
                (url, canonical_link, title, published_at_iso, summary)
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            return None
        except sqlite3.Error as e:
            logger.error(f"Ошибка при добавлении статьи {url}: {e}")
            return None

def is_article_posted(url: str) -> bool:
    with get_db_connection() as conn:
        canonical_link = _canonicalize_url(url)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM articles WHERE canonical_link = ?", (canonical_link,))
        return cursor.fetchone() is not None

def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def upsert_raw_article(url: str, title: str, published_at_iso: str, content: str) -> Optional[int]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            canonical_link = _canonicalize_url(url)
            content_hash = _sha256(content) if content else None
            cursor.execute("SELECT id FROM articles WHERE canonical_link = ?", (canonical_link,))
            row = cursor.fetchone()
            if row:
                article_id = row[0]
                cursor.execute(
                    "UPDATE articles SET url = ?, title = ?, published_at = ?, content = ?, content_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (url, title, published_at_iso, content, content_hash, article_id)
                )
            else:
                cursor.execute(
                    "INSERT INTO articles (url, canonical_link, title, published_at, content, content_hash) VALUES (?, ?, ?, ?, ?, ?)",
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
            "SELECT id, title, content, published_at FROM articles WHERE (summary_text IS NULL OR TRIM(summary_text) = '') AND published_at BETWEEN ? AND ? ORDER BY published_at ASC",
            (start_iso, end_iso),
        )
        return [dict(row) for row in cursor.fetchall()]

def backup_database_copy() -> Optional[str]:
    try:
        if not os.path.exists(DATABASE_NAME):
            return None
        timestamp = datetime.now(APP_TZ).strftime("%Y%m%d%H%M%S")
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
        cursor.execute("UPDATE articles SET summary_text = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (summary_text, article_id))
        conn.commit()

def dlq_record(entity_type: str, entity_ref: str, error_code: str = None, error_payload: str = None) -> None:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM dlq WHERE entity_type = ? AND entity_ref = ?", (entity_type, entity_ref))
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE dlq SET error_code = ?, error_payload = ?, attempts = attempts + 1, last_seen_at = CURRENT_TIMESTAMP WHERE id = ?", (error_code, error_payload, row[0]))
        else:
            cursor.execute("INSERT INTO dlq (entity_type, entity_ref, error_code, error_payload) VALUES (?, ?, ?, ?)", (entity_type, entity_ref, error_code, error_payload))
        conn.commit()

def get_dlq_size() -> int:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM dlq")
        return cursor.fetchone()[0]

def list_dlq_items(entity_type: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if entity_type:
            cursor.execute("SELECT * FROM dlq WHERE entity_type = ? ORDER BY last_seen_at DESC LIMIT ?", (entity_type, limit))
        else:
            cursor.execute("SELECT * FROM dlq ORDER BY last_seen_at DESC LIMIT ?", (limit,))
        return [dict(row) for row in cursor.fetchall()]

def delete_dlq_item(item_id: int) -> None:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM dlq WHERE id = ?", (item_id,))
        conn.commit()

def get_content_hash_groups(min_count: int = 2) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT content_hash AS hash, COUNT(*) AS cnt FROM articles WHERE content_hash IS NOT NULL GROUP BY content_hash HAVING COUNT(*) >= ? ORDER BY cnt DESC", (min_count,))
        return [dict(row) for row in cursor.fetchall()]

def list_articles_by_content_hash(content_hash: str) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, canonical_link, published_at FROM articles WHERE content_hash = ? ORDER BY published_at DESC", (content_hash,))
        return [dict(row) for row in cursor.fetchall()]

def get_summaries_for_date_range(start_date: str, end_date: str) -> List[str]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT summary_text FROM articles WHERE summary_text IS NOT NULL AND published_at BETWEEN ? AND ? ORDER BY published_at DESC", (start_date, end_date))
        return [item['summary_text'] for item in cursor.fetchall()]

def add_digest(period: str, content: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO digests (period, content) VALUES (?, ?)", (period, content))
        conn.commit()

def get_digests_for_period(days: int) -> List[str]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT content FROM digests WHERE created_at >= datetime('now', '-' || ? || ' days') ORDER BY created_at DESC", (days,))
        return [item['content'] for item in cursor.fetchall()]

def get_stats() -> Dict[str, Any]:
    stats: Dict[str, Any] = {'total_articles': 0, 'success': 0, 'failed': 0, 'skipped': 0, 'pending': 0, 'last_posted_article': {'title': "Нет", 'published_at': "Нет"}}
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM articles")
        stats['total_articles'] = cursor.fetchone()[0]
        cursor.execute("SELECT COALESCE(backfill_status, 'pending') as status, COUNT(*) as count FROM articles GROUP BY status")
        for row in cursor.fetchall():
            if row['status'] in stats:
                stats[row['status']] = row['count']
        cursor.execute("SELECT title, published_at FROM articles ORDER BY published_at DESC LIMIT 1")
        last_article_row = cursor.fetchone()
        if last_article_row:
            stats['last_posted_article'] = dict(last_article_row)
    return stats

def list_recent_articles(days: int = 7, limit: int = 200) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, canonical_link, content, published_at FROM articles WHERE published_at >= datetime('now', '-' || ? || ' days') AND content IS NOT NULL ORDER BY published_at DESC LIMIT ?", (days, limit))
        return [dict(row) for row in cursor.fetchall()]

def enqueue_publication(url: str, title: str, published_at: str, summary_text: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO pending_publications (url, title, published_at, summary_text, updated_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)", (url, title, published_at, summary_text))
            conn.commit()
        except sqlite3.IntegrityError:
            pass

def dequeue_batch(limit: int = 5) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pending_publications ORDER BY created_at ASC LIMIT ?", (limit,))
        return [dict(row) for row in cursor.fetchall()]

def delete_sent_publication(publication_id: int):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM pending_publications WHERE id = ?", (publication_id,))
        conn.commit()

def increment_attempt_count(publication_id: int, last_error: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE pending_publications SET attempts = attempts + 1, last_error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (last_error, publication_id))
        conn.commit()

def update_publication_summary(publication_id: int, summary_text: str):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE pending_publications SET summary_text = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (summary_text, publication_id))
        conn.commit()
