import sqlite3
from contextlib import contextmanager

DATABASE_NAME = "database/articles.db"

@contextmanager
def get_db_connection():
    """Контекстный менеджер для соединения с БД."""
    conn = sqlite3.connect(DATABASE_NAME)
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """
    Инициализирует базу данных, создавая две основные таблицы:
    - 'articles': для хранения основной информации о статьях.
    - 'summaries': для хранения сгенерированных резюме, связанных со статьями.
    Также создает таблицу 'digests' для аналитических сводок.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 1. Таблица для статей (без резюме)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT,
                published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. Таблица для резюме
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                summary_text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (article_id) REFERENCES articles (id)
            )
        """)

        # 3. Таблица для дайджестов (без изменений)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def add_article(url: str, title: str, published_at_iso: str | None = None) -> int | None:
    """
    Добавляет новую статью в таблицу 'articles' и возвращает ее ID.
    Если статья уже существует, просто возвращает ее ID.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            # Сначала проверяем, существует ли статья
            cursor.execute("SELECT id FROM articles WHERE url = ?", (url,))
            existing_article = cursor.fetchone()
            if existing_article:
                return existing_article[0]

            # Если нет, вставляем новую
            if published_at_iso:
                cursor.execute(
                    "INSERT INTO articles (url, title, published_at) VALUES (?, ?, ?)",
                    (url, title, published_at_iso)
                )
            else:
                cursor.execute(
                    "INSERT INTO articles (url, title) VALUES (?, ?)",
                    (url, title)
                )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            # На случай, если гонка потоков все же произойдет
            cursor.execute("SELECT id FROM articles WHERE url = ?", (url,))
            return cursor.fetchone()[0]
        except sqlite3.Error as e:
            print(f"Database error in add_article: {e}")
            return None

def add_summary(article_id: int, summary_text: str):
    """Добавляет резюме для статьи в таблицу 'summaries'."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO summaries (article_id, summary_text) VALUES (?, ?)",
                (article_id, summary_text)
            )
            conn.commit()
        except sqlite3.Error as e:
            print(f"Database error in add_summary: {e}")

def is_article_posted(url: str) -> bool:
    """Проверяет, была ли статья с таким URL уже опубликована."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM articles WHERE url = ?", (url,))
        return cursor.fetchone() is not None

def has_summary(article_id: int) -> bool:
    """Проверяет, есть ли у статьи с данным ID резюме."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM summaries WHERE article_id = ?", (article_id,))
        return cursor.fetchone() is not None

def add_digest(period: str, content: str):
    """Сохраняет новый сгенерированный дайджест в базу данных."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO digests (period, content) VALUES (?, ?)",
            (period, content)
        )
        conn.commit()

def get_summaries_for_period(days: int) -> list[str]:
    """
    Извлекает тексты резюме за последние `days` дней.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.summary_text 
            FROM summaries s
            JOIN articles a ON s.article_id = a.id
            WHERE a.published_at >= datetime('now', '-' || ? || ' days')
            ORDER BY a.published_at DESC
        """, (days,))
        return [item[0] for item in cursor.fetchall()]

def get_digests_for_period(days: int) -> list[str]:
    """
    Извлекает содержимое дайджестов, созданных за последние `days` дней.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT content FROM digests WHERE created_at >= datetime('now', '-' || ? || ' days') ORDER BY created_at DESC",
            (days,)
        )
        return [item[0] for item in cursor.fetchall()]

def get_stats() -> dict:
    """
    Возвращает статистику по опубликованным статьям.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM articles")
        total_articles = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM summaries")
        total_summaries = cursor.fetchone()[0]

        cursor.execute("SELECT title, published_at FROM articles ORDER BY published_at DESC LIMIT 1")
        last_article_row = cursor.fetchone()
        
        last_article = {
            "title": last_article_row[0] if last_article_row else "Нет",
            "published_at": last_article_row[1] if last_article_row else "Нет"
        }
        
        return {
            "total_articles": total_articles,
            "total_summaries": total_summaries,
            "last_article": last_article
        }

def get_articles_without_summary() -> list[tuple[int, str, str]]:
    """
    Возвращает список статей (id, url, title), у которых еще нет резюме.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT a.id, a.url, a.title
            FROM articles a
            LEFT JOIN summaries s ON a.id = s.article_id
            WHERE s.id IS NULL
            ORDER BY a.published_at ASC
        """)
        return cursor.fetchall()

def get_latest_article_timestamp() -> str | None:
    """
    Возвращает временную метку самой последней статьи в базе данных.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(published_at) FROM articles")
        result = cursor.fetchone()
        return result[0] if result else None

def get_article_urls_in_range(start_date_iso: str, end_date_iso: str) -> set[str]:
    """
    Возвращает множество URL-адресов статей в заданном диапазоне дат.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT url FROM articles WHERE published_at BETWEEN ? AND ?",
            (start_date_iso, end_date_iso)
        )
        return {row[0] for row in cursor.fetchall()}