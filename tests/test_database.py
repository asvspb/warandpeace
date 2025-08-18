import pytest
from pathlib import Path
from datetime import datetime
from src.database import init_db, add_article, is_article_posted, get_db_connection
from src import database

# Fixture to provide a temporary database path for each test
@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Provides a temporary database path for each test."""
    db = tmp_path / "test_articles.db"
    # Указываем, что используем тестовую БД
    database.DATABASE_NAME = str(db)
    # Инициализируем новую БД перед каждым тестом
    init_db()
    return db

def test_init_db(db_path: Path):
    """Тест: таблица 'articles' успешно создается."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='articles';")
        assert cursor.fetchone() is not None, "Таблица 'articles' не была создана."

def test_add_article(db_path: Path):
    """Тест: статья успешно добавляется в БД."""
    url = "http://example.com/article1"
    title = "Test Article 1"
    published_at = datetime.now().isoformat()
    summary = "Test Summary"
    add_article(url, title, published_at, summary)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT url, title FROM articles WHERE url = ?", (url,))
        result = cursor.fetchone()
        assert result is not None, "Статья не была добавлена."
        assert result[0] == url
        assert result[1] == title

def test_add_duplicate_article(db_path: Path):
    """Тест: добавление дубликата статьи не вызывает ошибок и не создает новую запись."""
    url = "http://example.com/article2"
    title = "Test Article 2"
    published_at = datetime.now().isoformat()
    summary = "Test Summary"
    
    add_article(url, title, published_at, summary) # Первое добавление
    add_article(url, title, published_at, summary) # Попытка добавить дубликат

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM articles WHERE url = ?", (url,))
        count = cursor.fetchone()[0]
        assert count == 1, "Дубликат статьи был добавлен."

def test_is_article_posted(db_path: Path):
    """Тест: функция правильно определяет опубликованные и неопубликованные статьи."""
    posted_url = "http://example.com/posted"
    not_posted_url = "http://example.com/not-posted"
    published_at = datetime.now().isoformat()
    summary = "Test Summary"
    
    add_article(posted_url, "Posted Article", published_at, summary)

    assert is_article_posted(posted_url), "Функция неверно определила опубликованную статью."
    assert not is_article_posted(not_posted_url), "Функция неверно определила неопубликованную статью."