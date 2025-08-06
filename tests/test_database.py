import unittest
import sqlite3
import os
from datetime import datetime
from src.database import init_db, add_article, is_article_posted, get_db_connection

class TestDatabase(unittest.TestCase):

    TEST_DB_NAME = "test_articles.db"

    def setUp(self):
        """Настройка перед каждым тестом: создаем чистую БД."""
        # Указываем, что используем тестовую БД
        from src import database
        database.DATABASE_NAME = self.TEST_DB_NAME
        
        # Удаляем старый файл БД, если он есть
        if os.path.exists(self.TEST_DB_NAME):
            os.remove(self.TEST_DB_NAME)
            
        # Инициализируем новую БД
        init_db()

    def tearDown(self):
        """Очистка после каждого теста: удаляем тестовую БД."""
        if os.path.exists(self.TEST_DB_NAME):
            os.remove(self.TEST_DB_NAME)

    def test_init_db(self):
        """Тест: таблица 'articles' успешно создается."""
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='articles';")
            self.assertIsNotNone(cursor.fetchone(), "Таблица 'articles' не была создана.")

    def test_add_article(self):
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
            self.assertIsNotNone(result, "Статья не была добавлена.")
            self.assertEqual(result[0], url)
            self.assertEqual(result[1], title)

    def test_add_duplicate_article(self):
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
            self.assertEqual(count, 1, "Дубликат статьи был добавлен.")

    def test_is_article_posted(self):
        """Тест: функция правильно определяет опубликованные и неопубликованные статьи."""
        posted_url = "http://example.com/posted"
        not_posted_url = "http://example.com/not-posted"
        published_at = datetime.now().isoformat()
        summary = "Test Summary"
        
        add_article(posted_url, "Posted Article", published_at, summary)

        self.assertTrue(is_article_posted(posted_url), "Функция неверно определила опубликованную статью.")
        self.assertFalse(is_article_posted(not_posted_url), "Функция неверно определила неопубликованную статью.")

if __name__ == '__main__':
    unittest.main()
