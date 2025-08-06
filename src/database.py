import sqlite3
from contextlib import contextmanager
import logging
from typing import Optional, Dict, Any, List

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
    Инициализирует базу данных, создавая таблицы.
    Таблица 'articles' теперь не содержит поля 'status'.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Удаляем старый индекс, если он существует
        cursor.execute("DROP INDEX IF EXISTS idx_articles_status")
        
        # Создаем новую таблицу без поля status
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                published_at TIMESTAMP NOT NULL,
                summary_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Копируем данные из старой таблицы в новую, если старая существует
        try:
            cursor.execute("INSERT INTO articles_new (id, url, title, published_at, summary_text, created_at) SELECT id, url, title, published_at, summary_text, created_at FROM articles")
            cursor.execute("DROP TABLE articles")
        except sqlite3.OperationalError:
            # Это произойдет, если таблицы 'articles' не существует (первый запуск)
            logger.info("Таблица 'articles' не найдена, создается новая структура.")
            pass

        # Переименовываем новую таблицу
        cursor.execute("ALTER TABLE articles_new RENAME TO articles")

        # Создаем индекс для published_at
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
        logger.info("База данных успешно инициализирована (схема без статусов).")

def add_article(url: str, title: str, published_at_iso: str, summary: str) -> Optional[int]:
    """
    Добавляет опубликованную статью в базу данных.
    Возвращает ID статьи, если она была добавлена, иначе None.
    """
    with get_db_connection() as conn:
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO articles (url, title, published_at, summary_text) VALUES (?, ?, ?, ?)",
                (url, title, published_at_iso, summary)
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
        cursor.execute("SELECT 1 FROM articles WHERE url = ?", (url,))
        return cursor.fetchone() is not None

def get_summaries_for_period(days: int) -> List[str]:
    """Извлекает тексты резюме статей за последние `days` дней."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT summary_text 
            FROM articles
            WHERE summary_text IS NOT NULL
              AND published_at >= datetime('now', '-' || ? || ' days')
            ORDER BY published_at DESC
        """, (days,))
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
    """Возвращает статистику по статьям в базе."""
    stats: Dict[str, Any] = {}
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM articles")
        stats['total_articles'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT title, published_at FROM articles ORDER BY published_at DESC LIMIT 1")
        last_article_row = cursor.fetchone()
        
        if last_article_row:
            stats['last_posted_article'] = {
                "title": last_article_row['title'],
                "published_at": last_article_row['published_at']
            }
        else:
            stats['last_posted_article'] = {
                "title": "Нет",
                "published_at": "Нет"
            }
        return stats
