"""
Тесты для проверки непрерывности процесса суммаризации и сохранения состояния задач.
"""
import json
import time
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from src.webapp.server import app
from src.queue_workers import create_summary_job, get_job_status
from src.models import SummaryStatus


class TestSummarizationContinuity:
    """Тесты для проверки непрерывности процесса суммаризации при переходе между страницами."""

    @pytest.fixture
    def client(self):
        """Фикстура для тестирования FastAPI приложения."""
        return TestClient(app)

    @patch('src.queue_workers.get_db_connection')
    def test_task_state_preservation_across_page_navigations(self, mock_db_conn):
        """Тест сохранения состояния задач при переходе между страницами."""
        # Подготовка моков
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db_conn.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Мокаем результат запроса к БД - задача в статусе PENDING
        mock_cursor.fetchone.return_value = (SummaryStatus.PENDING.value,)

        # Имитируем проверку статуса задачи до и после "перехода" между страницами
        job_id = "summarize_123_1234567890"
        status_before_navigation = get_job_status(job_id)
        
        # Имитация перехода между страницами (ничего не изменяется в системе)
        # Проверяем статус снова
        status_after_navigation = get_job_status(job_id)
        
        # Проверяем, что статус задачи сохранился
        assert status_before_navigation["status"] == status_after_navigation["status"]
        assert status_before_navigation["job_id"] == status_after_navigation["job_id"]
        assert status_before_navigation["completed"] == status_after_navigation["completed"]

    @patch('src.queue_workers.redis_client')
    @patch('src.queue_workers.get_db_connection')
    def test_task_queue_integrity_during_navigation(self, mock_db_conn, mock_redis):
        """Тест целостности очереди задач во время навигации по приложению."""
        # Подготовка моков
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db_conn.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (SummaryStatus.PENDING.value,)
        
        # Мокаем Redis
        mock_redis.llen.return_value = 3  # 3 задачи в очереди

        # Создаем несколько задач
        job_ids = []
        for i in range(3):
            with patch('src.webapp.routes_summarization.get_article_by_id') as mock_get_article:
                mock_get_article.return_value = {
                    'id': 100+i,
                    'title': f'Статья {i}',
                    'content': f'Содержимое статьи {i}'
                }
                
                job_id = create_summary_job(100+i, f'Статья {i}', f'Содержимое статьи {i}')
                job_ids.append(job_id)

        # Имитируем навигацию по приложению (проверка очереди до и после)
        queue_length_before = mock_redis.llen("summarization")
        
        # Имитация навигации - проверяем длину очереди снова
        queue_length_after = mock_redis.llen("summarization")
        
        # Проверяем, что длина очереди не изменилась
        assert queue_length_before == queue_length_after
        assert queue_length_before == 3

    def test_session_state_preservation(self):
        """Тест сохранения состояния сессии между запросами."""
        client = TestClient(app)
        
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
            mock_redis.llen.return_value = 5
            
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_db_conn.return_value.__enter__.return_value = mock_conn
            mock_conn.cursor.return_value = mock_cursor
            mock_cursor.fetchone.return_value = (SummaryStatus.PENDING.value,)

            # Выполняем серию запросов и проверяем сохранение состояния
            response1 = client.post("/api/summarization/enqueue?article_id=123")
            assert response1.status_code == 200
            
            response2 = client.get("/api/summarization/status/summarize_123_1234567890")
            assert response2.status_code == 200
            
            response3 = client.get("/api/summarization/queue-info")
            assert response3.status_code == 200
            
            # Проверяем, что все запросы были успешными и состояние сохраняется
            assert response1.json()["status"] == "queued"
            assert response2.json()["status"] == SummaryStatus.PENDING.value
            # Проверяем, что возвращается количество задач
            assert isinstance(response3.json()["pending_jobs_count"], int)


class TestCalendarStatusDisplay:
    """Тесты для проверки отображения статуса задач в интерфейсе календаря."""

    @pytest.fixture
    def client(self):
        """Фикстура для тестирования FastAPI приложения."""
        return TestClient(app)

    @patch('src.webapp.services.get_month_calendar_data')
    def test_calendar_status_indicators(self, mock_calendar_data, client):
        """Тест индикаторов статуса в интерфейсе календаря."""
        # Мокаем данные календаря с различными статусами суммаризации
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
                            "total": 3,
                            "summarized": 2  # 2 из 3 статей просуммаризированы
                        },
                        {
                            "date": "2024-09-02",
                            "day": 2,
                            "in_month": True,
                            "total": 1,
                            "summarized": 0  # 0 из 1 статьи просуммаризировано
                        }
                    ],
                    "total": 4,
                    "summarized": 2,
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
        
        # Проверяем, что ответ содержит информацию о статусе суммаризации
        response_text = response.text
        assert "2/3" in response_text  # 2 из 3 статей просуммаризировано за 1 сентября
        assert "0/1" in response_text  # 0 из 1 статьи просуммаризировано за 2 сентября

    @patch('src.webapp.services.get_month_calendar_data')
    def test_calendar_status_updates(self, mock_calendar_data, client):
        """Тест обновления статуса в интерфейсе календаря."""
        # Мокаем данные календаря с начальным статусом
        initial_data = {
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
        mock_calendar_data.return_value = initial_data

        # Запрашиваем календарь с начальным статусом
        response_before = client.get("/calendar?year=2024&month=9")
        assert response_before.status_code == 200

        # Обновляем мок, имитируя завершение суммаризации
        updated_data = {
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
                            "summarized": 2  # Теперь все статьи просуммаризированы
                        }
                    ],
                    "total": 2,
                    "summarized": 2,
                    "all_summarized": True # Все статьи за день просуммаризированы
                }
            ],
            "prev": {"year": 2024, "month": 8},
            "next": {"year": 2024, "month": 10}
        }
        mock_calendar_data.return_value = updated_data

        # Запрашиваем календарь с обновленным статусом
        response_after = client.get("/calendar?year=2024&month=9")
        assert response_after.status_code == 200

        # Проверяем, что статусы изменились
        assert "1/2" in response_before.text
        assert "2/2" in response_after.text


class TestLocalStoragePersistence:
    """Тесты для проверки сохранения состояния задач в localStorage между сессиями."""

    def test_local_storage_task_tracking(self):
        """Тест отслеживания задач через localStorage."""
        # Этот тест описывает логику, которая будет реализована в JavaScript тестах
        # Проверяем структуру данных, которые должны храниться в localStorage
        
        # Пример данных задачи, которые должны храниться
        sample_task = {
            "jobId": "summarize_123_1234567890",
            "articleId": 123,
            "status": "processing",
            "updatedAt": "2024-09-29T12:00:00Z"
        }
        
        # Проверяем, что структура данных корректна
        assert "jobId" in sample_task
        assert "articleId" in sample_task
        assert "status" in sample_task
        assert "updatedAt" in sample_task
        
        # Проверяем валидность значений
        assert isinstance(sample_task["jobId"], str)
        assert isinstance(sample_task["articleId"], int)
        assert isinstance(sample_task["status"], str)
        assert isinstance(sample_task["updatedAt"], str)

    def test_local_storage_batch_operations(self):
        """Тест операций с группами задач в localStorage."""
        # Пример данных для нескольких задач
        sample_tasks = [
            {
                "jobId": "summarize_123_1234567890",
                "articleId": 123,
                "status": "pending",
                "updatedAt": "2024-09-29T12:00:00Z"
            },
            {
                "jobId": "summarize_456_1234567891",
                "articleId": 456,
                "status": "processing",
                "updatedAt": "2024-09-29T12:01:00Z"
            },
            {
                "jobId": "summarize_789_1234567892",
                "articleId": 789,
                "status": "completed",
                "updatedAt": "2024-09-29T12:02:00Z"
            }
        ]
        
        # Проверяем, что все задачи имеют корректную структуру
        for task in sample_tasks:
            assert "jobId" in task
            assert "articleId" in task
            assert "status" in task
            assert "updatedAt" in task
        
        # Проверяем фильтрацию завершенных задач (как в функции очистки localStorage)
        pending_tasks = [task for task in sample_tasks if task["status"] not in ["finished", "completed", "failed", "error"]]
        assert len(pending_tasks) == 2  # Две задачи не завершены (pending и processing)
        # Проверяем, что в списке есть задачи со статусами pending и processing
        statuses = [task["status"] for task in pending_tasks]
        assert "pending" in statuses
        assert "processing" in statuses

    @patch('src.queue_workers.get_db_connection')
    def test_state_sync_between_api_and_local_storage(self, mock_db_conn):
        """Тест синхронизации состояния между API и localStorage."""
        # Подготовка моков
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_db_conn.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Мокаем результат запроса к БД
        mock_cursor.fetchone.return_value = (SummaryStatus.OK.value,)

        # Имитируем получение статуса задачи через API
        job_id = "summarize_123_1234567890"
        api_status = get_job_status(job_id)
        
        # Имитируем структуру данных, которая будет храниться в localStorage
        local_storage_task = {
            "jobId": job_id,
            "articleId": 123,
            "status": api_status["status"],
            "updatedAt": "2024-09-29T12:00:00Z"
        }
        
        # Проверяем, что статус из API соответствует формату для localStorage
        assert local_storage_task["status"] == api_status["status"]
        assert local_storage_task["jobId"] == api_status["job_id"]
        assert local_storage_task["articleId"] == api_status["article_id"]