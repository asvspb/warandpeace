import pytest
from datetime import datetime

from src.database import init_db, add_article, is_article_posted, get_db_connection


@pytest.fixture(scope="module", autouse=True)
def ensure_schema():
    # Гарантируем, что схема БД существует перед тестами модуля
    init_db()
    yield


def test_init_db():
    """Тест: таблица 'articles' существует (через information_schema)."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # PostgreSQL: проверяем наличие таблицы в схеме public
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'articles'
            LIMIT 1
            """
        )
        assert cursor.fetchone() is not None, "Таблица 'articles' не была создана."


def test_add_article():
    """Тест: статья успешно добавляется в БД."""
    url = "http://example.com/article1"
    title = "Test Article 1"
    published_at = datetime.now().isoformat()
    summary = "Test Summary"
    try:
        add_article(url, title, published_at, summary)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT url, title FROM articles WHERE url = ?", (url,))
            result = cursor.fetchone()
            assert result is not None, "Статья не была добавлена."
            assert result[0] == url
            assert result[1] == title
    finally:
        # cleanup
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM articles WHERE url = ?", (url,))
            conn.commit()


def test_add_duplicate_article():
    """Тест: добавление дубликата статьи не создает новую запись (UPSERT DO NOTHING)."""
    url = "http://example.com/article2"
    title = "Test Article 2"
    published_at = datetime.now().isoformat()
    summary = "Test Summary"
    try:
        add_article(url, title, published_at, summary)  # Первое добавление
        add_article(url, title, published_at, summary)  # Дубликат
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM articles WHERE url = ?", (url,))
            count = int(cursor.fetchone()[0])
            assert count == 1, "Дубликат статьи был добавлен."
    finally:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM articles WHERE url = ?", (url,))
            conn.commit()


def test_is_article_posted():
    """Тест: функция правильно определяет опубликованные и неопубликованные статьи."""
    posted_url = "http://example.com/posted"
    not_posted_url = "http://example.com/not-posted"
    published_at = datetime.now().isoformat()
    summary = "Test Summary"
    try:
        add_article(posted_url, "Posted Article", published_at, summary)
        assert is_article_posted(posted_url), "Функция неверно определила опубликованную статью."
        assert not is_article_posted(not_posted_url), "Функция неверно определила неопубликованную статью."
    finally:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM articles WHERE url = ?", (posted_url,))
            conn.commit()
