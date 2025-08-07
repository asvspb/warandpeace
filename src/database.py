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
    Инициализирует или обновляет схему базы данных.
    - Добавляет таблицу 'articles' со всеми необходимыми полями, включая 'backfill_status'.
    - Выполняет миграцию данных из старой схемы, если это необходимо.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 1. Проверяем, существует ли уже новая колонка
        cursor.execute("PRAGMA table_info(articles)")
        columns = [column['name'] for column in cursor.fetchall()]
        
        if 'backfill_status' in columns:
            logger.info("Колонка 'backfill_status' уже существует. Миграция не требуется.")
        else:
            logger.info("Колонка 'backfill_status' не найдена. Начинаем миграцию схемы...")
            
            # 2. Создаем новую таблицу с правильной схемой
            cursor.execute("""
                CREATE TABLE articles_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    published_at TIMESTAMP NOT NULL,
                    summary_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    backfill_status TEXT CHECK(backfill_status IN ('success', 'failed', 'skipped'))
                )
            """)

            # 3. Копируем данные из старой таблицы (если она существует)
            try:
                # Выбираем только те колонки, которые есть в обеих таблицах
                cursor.execute("INSERT INTO articles_new (id, url, title, published_at, summary_text, created_at) SELECT id, url, title, published_at, summary_text, created_at FROM articles")
                # 4. Удаляем старую таблицу
                cursor.execute("DROP TABLE articles")
                logger.info("Старая таблица 'articles' удалена.")
            except sqlite3.OperationalError:
                logger.info("Старая таблица 'articles' не найдена, будет создана новая.")
                pass  # Игнорируем ошибку, если таблицы 'articles' не было

            # 5. Переименовываем новую таблицу
            cursor.execute("ALTER TABLE articles_new RENAME TO articles")
            logger.info("Таблица 'articles' успешно обновлена до новой схемы.")

        # 6. Создаем индексы
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles (published_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_backfill_status ON articles (backfill_status)")

        # 7. Создаем таблицу для дайджестов (без изменений)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
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
