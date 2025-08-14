import sqlite3
import hashlib
from contextlib import contextmanager
import logging
import os
import shutil
from datetime import datetime
from typing import Optional, Dict, Any, List

DATABASE_NAME = "/app/database/articles.db"
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
        
        logger.info("Инициализация базы данных завершена.")


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
