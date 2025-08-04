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
    Инициализирует базу данных, создает и обновляет таблицы.
    - Добавляет поле 'summary' в таблицу 'articles'.
    - Создает таблицу 'digests'.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 1. Модификация таблицы articles
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT,
                summary TEXT,
                published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Проверка и добавление колонки summary для обратной совместимости
        try:
            cursor.execute("ALTER TABLE articles ADD COLUMN summary TEXT;")
        except sqlite3.OperationalError:
            # Колонка уже существует
            pass

        # 2. Создание таблицы digests
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS digests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def add_article(url: str, title: str, summary: str):
    """Добавляет новую статью и ее краткое содержание в базу данных."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO articles (url, title, summary) VALUES (?, ?, ?)",
                (url, title, summary)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # Статья с таким URL уже существует
            pass

def is_article_posted(url: str) -> bool:
    """Проверяет, была ли статья с таким URL уже опубликована."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM articles WHERE url = ?", (url,))
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
    Извлекает сводки статей, опубликованные за последние `days` дней.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT summary FROM articles WHERE published_at >= datetime('now', '-' || ? || ' days') AND summary IS NOT NULL ORDER BY published_at DESC",
            (days,)
        )
        # fetchall() возвращает список кортежей [(summary1,), (summary2,)]
        # Преобразуем его в простой список строк
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
        
        # Общее количество статей
        cursor.execute("SELECT COUNT(*) FROM articles")
        total_articles = cursor.fetchone()[0]
        
        # Последняя опубликованная статья
        cursor.execute("SELECT title, published_at FROM articles ORDER BY published_at DESC LIMIT 1")
        last_article_row = cursor.fetchone()
        
        last_article = {
            "title": last_article_row[0] if last_article_row else "Нет",
            "published_at": last_article_row[1] if last_article_row else "Нет"
        }
        
        return {
            "total_articles": total_articles,
            "last_article": last_article
        }
