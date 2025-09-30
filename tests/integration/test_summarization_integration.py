"""
Интеграционные тесты для архитектурного решения фоновой суммаризации.
Проверяют взаимодействие между API-эндпоинтами, очередью задач и клиентской частью.
"""
import json
import time
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from src.webapp.server import app
from src.queue_workers import create_summary_job, get_job_status
from src.models import SummaryStatus


class TestSummarizationIntegration:
    """Интеграционные тесты для проверки взаимодействия между компонентами."""

    @pytest.fixture
    def client(self):
        """Фикстура для тестирования FastAPI приложения."""
        return TestClient(app)

    @patch('src.queue_workers.redis_client')
    @patch('src.queue_workers.get_db_connection')
    @patch('src.summarizer.summarize_text_background')
    def test_api_to_queue_integration(self, mock_summarize, mock_db_conn, mock_redis, client):
        """Тест интеграции API-эндпоинта с очередью задач."""
        # Подготовка моков
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db_conn.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Мокаем успешную суммаризацию
        mock_summarize.return_value = "Тестовый результат суммаризации"
        
        # Мокаем Redis
        mock_redis.lpush.return_value = 1
        mock_redis.brpop.return_value = (b'summarization', json.dumps({
            "article_id": 123,
            "title": "Тестовая статья",
            "content": "Содержимое тестовой статьи"
        }).encode())

        # Подготовка данных статьи
        with patch('src.webapp.routes_summarization.get_article_by_id') as mock_get_article:
            mock_get_article.return_value = {
                'id': 123,
                'title': 'Тестовая статья',
                'content': 'Содержимое тестовой статьи'
            }

            # Вызов эндпоинта для постановки задачи в очередь
            response = client.post("/api/summarization/enqueue?article_id=123")

            # Проверки
            assert response.status_code == 200
            data = response.json()
            assert "job_id" in data
            assert data["status"] == "queued"
            assert data["article_id"] == 123

            # Проверяем, что задача была помещена в очередь
            mock_redis.lpush.assert_called_once()

    @patch('src.queue_workers.get_db_connection')
    def test_job_status_tracking(self, mock_db_conn, client):
        """Тест отслеживания статуса задачи через API."""
        # Подготовка моков
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db_conn.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Мокаем результат запроса к БД
        mock_cursor.fetchone.return_value = (SummaryStatus.OK.value,)

        # Вызов эндпоинта получения статуса задачи
        job_id = "summarize_123_1234567890"
        response = client.get(f"/api/summarization/status/{job_id}")

        # Проверки
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert data["status"] == SummaryStatus.OK.value
        assert data["completed"] is True

    @patch('src.queue_workers.get_db_connection')
    @patch('src.queue_workers.redis_client')
    def test_batch_enqueue_integration(self, mock_redis, mock_db_conn, client):
        """Тест интеграции пакетной постановки задач в очередь."""
        # Подготовка моков
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db_conn.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Мокаем Redis
        mock_redis.lpush.return_value = 1

        # Подготовка данных статей
        article_ids = [123, 456, 789]
        def mock_get_article(article_id):
            articles = {
                123: {'id': 123, 'title': 'Статья 1', 'content': 'Содержимое статьи 1'},
                456: {'id': 456, 'title': 'Статья 2', 'content': 'Содержимое статьи 2'},
                789: {'id': 789, 'title': 'Статья 3', 'content': 'Содержимое статьи 3'}
            }
            return articles.get(article_id)
        
        with patch('src.webapp.routes_summarization.get_article_by_id', side_effect=mock_get_article):
            # Вызов эндпоинта для пакетной постановки задач в очередь
            response = client.post(
                "/api/summarization/enqueue-batch",
                json=article_ids
            )

            # Проверки
            assert response.status_code == 200
            data = response.json()
            assert data["total_queued"] == 3
            assert data["total_errors"] == 0
            assert len(data["queued_jobs"]) == 3

            # Проверяем, что задачи были помещены в очередь
            assert mock_redis.lpush.call_count == 3

    @patch('src.queue_workers.redis_client')
    def test_queue_info_endpoint(self, mock_redis, client):
        """Тест эндпоинта получения информации о состоянии очереди."""
        # Мокаем длину очереди
        mock_redis.llen.return_value = 5

        # Вызов эндпоинта
        response = client.get("/api/summarization/queue-info")

        # Проверки
        assert response.status_code == 200
        data = response.json()
        assert data["pending_jobs_count"] == 5
        assert data["queue_name"] == "summarization"


class TestFrontendIntegration:
    """Интеграционные тесты для проверки взаимодействия клиентской части с API."""

    @pytest.fixture
    def client(self):
        """Фикстура для тестирования FastAPI приложения."""
        return TestClient(app)

    def test_calendar_frontend_integration(self, client):
        """Тест интеграции интерфейса календаря с API суммаризации."""
        # Мокаем статьи для отображения в календаре
        with patch('src.webapp.services.get_month_calendar_data') as mock_calendar_data:
            mock_calendar_data.return_value = {
                "year": 2024,
                "month": 9,
                "month_name": "Сентябрь",
                "weeks": [
                    {
                        "days": [
                            {
                                "date": "2024-09-01",
                                "day": 1,
                                "in_month": True,
                                "total": 2,
                                "summarized": 1
                            }
                        ],
                        "total": 2,
                        "summarized": 1,
                        "all_summarized": False
                    }
                ],
                "prev": {"year": 2024, "month": 8},
                "next": {"year": 2024, "month": 10}
            }

            # Запрашиваем страницу календаря
            response = client.get("/calendar?year=2024&month=9")

            # Проверяем успешный ответ
            assert response.status_code == 200
            # Проверяем, что страница содержит элементы календаря
            assert b"calendar" in response.content.lower()

    @patch('src.queue_workers.get_db_connection')
    def test_status_polling_integration(self, mock_db_conn, client):
        """Тест интеграции опроса статуса задач через API."""
        # Подготовка моков
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db_conn.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Мокаем результат запроса к БД
        mock_cursor.fetchone.return_value = (SummaryStatus.PENDING.value,)

        # Вызов эндпоинта получения статуса задачи (имитация опроса)
        job_id = "summarize_456_1234567891"
        response = client.get(f"/api/summarization/status/{job_id}")

        # Проверки
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert data["status"] == SummaryStatus.PENDING.value
        assert data["completed"] is False

    def test_api_response_format_consistency(self, client):
        """Тест согласованности формата ответов API для использования в клиентской части."""
        # Подготовка моков
        with patch('src.webapp.routes_summarization.get_article_by_id') as mock_get_article, \
             patch('src.queue_workers.create_summary_job') as mock_create_job, \
             patch('src.queue_workers.get_db_connection') as mock_db_conn, \
             patch('src.queue_workers.redis_client') as mock_redis:
            
            # Настройка моков
            mock_get_article.return_value = {
                'id': 123,
                'title': 'Тестовая статья',
                'content': 'Содержимое тестовой статьи'
            }
            mock_create_job.return_value = "summarize_123_1234567890"
            mock_redis.lpush.return_value = 1
            
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_db_conn.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = (SummaryStatus.OK.value,)

            # Вызов эндпоинта для постановки задачи
            enqueue_response = client.post("/api/summarization/enqueue?article_id=123")
            assert enqueue_response.status_code == 200
            
            # Проверяем формат ответа
            enqueue_data = enqueue_response.json()
            assert "job_id" in enqueue_data
            assert "article_id" in enqueue_data
            assert "status" in enqueue_data

            # Вызов эндпоинта для проверки статуса
            status_response = client.get(f"/api/summarization/status/summarize_123_1234567890")
            assert status_response.status_code == 200
            
            # Проверяем формат ответа статуса
            status_data = status_response.json()
            assert "job_id" in status_data
            assert "status" in status_data
            assert "completed" in status_data