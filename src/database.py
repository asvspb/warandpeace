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
    """Инициализирует базу данных и создает таблицу, если она не существует."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                title TEXT,
                published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def add_article(url: str, title: str):
    """Добавляет новую статью в базу данных."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO articles (url, title) VALUES (?, ?)", (url, title))
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
