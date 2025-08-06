import sqlite3
from contextlib import contextmanager
import logging

DATABASE_NAME = "database/articles.db"
logger = logging.getLogger(__name__)

@contextmanager
def get_db_connection():
    """Контекстный менеджер для соединения с БД."""
    try:
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
    """
    Инициализирует базу данных, создавая таблицу articles с полем статуса.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                published_at TIMESTAMP NOT NULL,
                summary_text TEXT,
                status TEXT NOT NULL DEFAULT 'new', -- new, summarizing, summarized, failed, posted
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Индексы для ускорения выборок по статусу и дате
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_status ON articles (status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles (published_at)")
        
        # Таблица для дайджестов остается без изменений
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        logger.info("База данных успешно инициализирована со схемой 'status'.")

def add_article(url: str, title: str, published_at_iso: str) -> int | None:
    """
    Добавляет новую статью со статусом 'new'.
    Возвращает ID статьи, если она была добавлена, иначе None.
    """
    with get_db_connection() as conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO articles (url, title, published_at, status) VALUES (?, ?, ?, 'new')",
                (url, title, published_at_iso)
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            logger.warning(f"Статья с URL {url} уже существует в базе. Пропускаю добавление.")
            return None
        except sqlite3.Error as e:
            logger.error(f"Ошибка при добавлении статьи {url}: {e}")
            return None

def get_article_by_url(url: str) -> sqlite3.Row | None:
    """Находит статью по ее URL."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM articles WHERE url = ?", (url,))
        return cursor.fetchone()

def set_article_status(article_id: int, status: str):
    """Обновляет статус статьи."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE articles SET status = ? WHERE id = ?",
            (status, article_id)
        )
        conn.commit()

def update_article_summary(article_id: int, summary_text: str):
    """Добавляет резюме к статье."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE articles SET summary_text = ? WHERE id = ?",
            (summary_text, article_id)
        )
        conn.commit()

def get_articles_by_status(status: str, limit: int = 10) -> list[sqlite3.Row]:
    """Получает список статей с определенным статусом."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM articles WHERE status = ? ORDER BY published_at ASC LIMIT ?", (status, limit))
        return cursor.fetchall()

def get_summaries_for_period(days: int) -> list[str]:
    """Извлекает тексты резюме опубликованных статей за последние `days` дней."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT summary_text 
            FROM articles
            WHERE status = 'posted' AND summary_text IS NOT NULL
              AND published_at >= datetime('now', '-' || ? || ' days')
            ORDER BY published_at DESC
        """, (days,))
        return [item['summary_text'] for item in cursor.fetchall()]

# Функции для дайджестов и статистики, адаптированные под новую схему
def add_digest(period: str, content: str):
    """Сохраняет новый дайджест."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO digests (period, content) VALUES (?, ?)",
            (period, content)
        )
        conn.commit()

def get_digests_for_period(days: int) -> list[str]:
    """Извлекает дайджесты за последние `days` дней."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT content FROM digests WHERE created_at >= datetime('now', '-' || ? || ' days') ORDER BY created_at DESC",
            (days,)
        )
        return [item['content'] for item in cursor.fetchall()]

def get_stats() -> dict:
    """Возвращает статистику по статьям в базе."""
    stats = {}
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Общее количество статей
        cursor.execute("SELECT COUNT(*) FROM articles")
        stats['total_articles'] = cursor.fetchone()[0]
        
        # Статистика по статусам
        cursor.execute("SELECT status, COUNT(*) FROM articles GROUP BY status")
        stats['by_status'] = {row['status']: row['COUNT(*)'] for row in cursor.fetchall()}

        # Последняя опубликованная статья
        cursor.execute("SELECT title, published_at FROM articles WHERE status = 'posted' ORDER BY published_at DESC LIMIT 1")
        last_article_row = cursor.fetchone()
        
        stats['last_posted_article'] = {
            "title": last_article_row['title'] if last_article_row else "Нет",
            "published_at": last_article_row['published_at'] if last_article_row else "Нет"
        }
        return stats
