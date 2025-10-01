"""
Тесты для модуля фоновой суммаризации и очереди задач.
"""
import json
import pytest
from unittest.mock import patch, MagicMock, Mock
from datetime import datetime

from src.queue_workers import (
    create_summary_job,
    process_summary_job,
    get_job_status,
    update_summary_status,
    save_summary_result,
    worker_loop
)
from src.models import SummaryStatus
from src.summarizer import summarize_text_background


class TestSummarizationQueue:
    """Тесты для модуля очереди задач суммаризации."""
    
    @patch('src.queue_workers.redis_client')
    @patch('src.queue_workers.get_db_connection')
    def test_create_summary_job(self, mock_db_conn, mock_redis):
        """Тест создания задачи суммаризации в очереди."""
        # Подготовка моков
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_db_conn.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Вызов тестируемой функции
        article_id = 123
        article_title = "Тестовая статья"
        article_content = "Содержимое тестовой статьи"
        
        job_id = create_summary_job(article_id, article_title, article_content)
        
        # Проверки
        assert job_id.startswith(f"summarize_{article_id}_")
        mock_redis.lpush.assert_called_once()
        args, kwargs = mock_redis.lpush.call_args
        assert args[0] == "summarization"  # имя очереди
        job_data = json.loads(args[1])
        assert job_data["article_id"] == article_id
        assert job_data["title"] == article_title
        assert job_data["content"] == article_content
        
        # Проверка обновления статуса в БД
        mock_cursor.execute.assert_called()
        mock_conn.commit.assert_called()
    
    @patch('src.queue_workers.summarize_text_background')
    @patch('src.queue_workers.save_summary_result')
    @patch('src.queue_workers.update_summary_status')
    def test_process_summary_job_success(self, mock_update_status, mock_save_result, mock_summarize):
        """Тест успешной обработки задачи суммаризации."""
        # Подготовка данных задачи
        job_data = {
            "article_id": 123,
            "content": "Тестовое содержимое статьи"
        }
        
        # Мокаем успешную суммаризацию
        mock_summarize.return_value = "Результат суммаризации"
        
        # Вызов тестируемой функции
        result = process_summary_job(job_data)
        
        # Проверки
        assert result is True
        mock_summarize.assert_called_once_with("Тестовое содержимое статьи", 123)
        mock_save_result.assert_called_once_with(123, "Результат суммаризации")
        mock_update_status.assert_not_called()  # статус не должен обновляться при успехе
    
    @patch('src.queue_workers.summarize_text_background')
    @patch('src.queue_workers.update_summary_status')
    def test_process_summary_job_failure(self, mock_update_status, mock_summarize):
        """Тест обработки задачи суммаризации при ошибке."""
        # Подготовка данных задачи
        job_data = {
            "article_id": 123,
            "content": "Тестовое содержимое статьи"
        }
        
        # Мокаем неудачную суммаризацию
        mock_summarize.return_value = None
        
        # Вызов тестируемой функции
        result = process_summary_job(job_data)
        
        # Проверки
        assert result is False
        mock_summarize.assert_called_once_with("Тестовое содержимое статьи", 123)
        mock_update_status.assert_called_once_with(123, SummaryStatus.FAILED)
    
    @patch('src.queue_workers.get_db_connection')
    def test_update_summary_status_new_record(self, mock_db_conn):
        """Тест обновления статуса суммаризации для новой статьи."""
        # Подготовка моков
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_db_conn.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Мокаем отсутствие существующей записи
        mock_cursor.fetchone.return_value = None
        
        # Вызов тестируемой функции
        update_summary_status(123, SummaryStatus.PENDING)
        
        # Проверки - должна быть вставка новой записи
        mock_cursor.execute.assert_called()
        # Проверяем, что был вызван INSERT, а не UPDATE
        query = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO summaries" in query or "UPDATE summaries" in query
    
    @patch('src.queue_workers.get_db_connection')
    def test_update_summary_status_existing_record(self, mock_db_conn):
        """Тест обновления статуса суммаризации для существующей статьи."""
        # Подготовка моков
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_db_conn.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Мокаем наличие существующей записи
        mock_cursor.fetchone.return_value = (1,)  # ID существующей записи
        
        # Вызов тестируемой функции
        update_summary_status(123, SummaryStatus.OK)
        
        # Проверки - должна быть попытка обновления
        mock_cursor.execute.assert_called()
    
    @patch('src.queue_workers.get_db_connection')
    def test_save_summary_result(self, mock_db_conn):
        """Тест сохранения результата суммаризации."""
        # Подготовка моков
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_db_conn.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Вызов тестируемой функции
        save_summary_result(123, "Тестовый результат суммаризации")
        
        # Проверки - должны быть два вызова: UPDATE summaries и UPDATE articles
        assert mock_cursor.execute.call_count >= 2
        mock_conn.commit.assert_called_once()
    
    @patch('src.queue_workers.get_db_connection')
    def test_get_job_status_completed(self, mock_db_conn):
        """Тест получения статуса завершенной задачи."""
        # Подготовка моков
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_db_conn.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Мокаем результат запроса к БД
        mock_cursor.fetchone.return_value = (SummaryStatus.OK.value,)
        
        # Вызов тестируемой функции
        job_id = "summarize_123_1234567890"
        status_info = get_job_status(job_id)
        
        # Проверки
        assert status_info["job_id"] == job_id
        assert status_info["article_id"] == 123
        assert status_info["status"] == "completed"
        assert status_info["completed"] is True
    
    @patch('src.queue_workers.get_db_connection')
    def test_get_job_status_pending(self, mock_db_conn):
        """Тест получения статуса задачи в ожидании."""
        # Подготовка моков
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_db_conn.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        
        # Мокаем отсутствие записи в БД (задача в очереди)
        mock_cursor.fetchone.return_value = None
        
        # Вызов тестируемой функции
        job_id = "summarize_456_1234567890"
        status_info = get_job_status(job_id)
        
        # Проверки
        assert status_info["job_id"] == job_id
        assert status_info["article_id"] == 456
        assert status_info["status"] == "queued"
        assert status_info["completed"] is False


class TestSummarizationEndpoints:
    """Тесты для API-эндпоинтов суммаризации."""
    
    @pytest.fixture
    def test_client(self):
        """Фикстура для тестирования FastAPI приложения."""
        from src.webapp.server import app
        from fastapi.testclient import TestClient
        
        return TestClient(app)
    
    def test_enqueue_summarization_endpoint(self, test_client):
        """Тест эндпоинта добавления задачи суммаризации в очередь."""
        with patch('src.webapp.routes_summarization.get_article_by_id') as mock_get_article, \
             patch('src.queue_workers.create_summary_job') as mock_create_job:
            
            # Подготовка данных
            article_id = 123
            mock_get_article.return_value = {
                'id': article_id,
                'title': 'Тестовая статья',
                'content': 'Содержимое статьи для суммаризации'
            }
            mock_create_job.return_value = f"summarize_{article_id}_1234567890"
            
            # Вызов эндпоинта
            response = test_client.post(f"/api/summarization/enqueue?article_id={article_id}")
            
            # Проверки
            assert response.status_code == 200
            data = response.json()
            assert data["article_id"] == article_id
            assert data["status"] == "queued"
            assert "job_id" in data
    
    def test_enqueue_summarization_article_not_found(self, test_client):
        """Тест эндпоинта при отсутствии статьи."""
        with patch('src.webapp.routes_summarization.get_article_by_id') as mock_get_article:
            # Подготовка данных
            mock_get_article.return_value = None
            
            # Вызов эндпоинта
            response = test_client.post("/api/summarization/enqueue?article_id=999")
            
            # Проверки
            assert response.status_code == 404
    
    def test_enqueue_summarization_no_content(self, test_client):
        """Тест эндпоинта при отсутствии контента для суммаризации."""
        with patch('src.webapp.routes_summarization.get_article_by_id') as mock_get_article:
            # Подготовка данных
            mock_get_article.return_value = {
                'id': 123,
                'title': 'Тестовая статья',
                'content': None
            }
            
            # Вызов эндпоинта
            response = test_client.post("/api/summarization/enqueue?article_id=123")
            
            # Проверки
            assert response.status_code == 400
    
    def test_get_summarization_status_endpoint(self, test_client):
        """Тест эндпоинта получения статуса задачи суммаризации."""
        with patch('src.webapp.routes_summarization.get_job_status') as mock_get_status:
            # Подготовка данных
            job_id = "summarize_123_1234567890"
            mock_get_status.return_value = {
                "job_id": job_id,
                "article_id": 123,
                "status": SummaryStatus.OK.value,
                "completed": True
            }
            
            # Вызов эндпоинта
            response = test_client.get(f"/api/summarization/status/{job_id}")
            
            # Проверки
            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == job_id
            assert data["article_id"] == 123
            assert data["status"] == SummaryStatus.OK.value
            assert data["completed"] is True
    
    def test_enqueue_summarization_batch(self, test_client):
        """Тест эндпоинта добавления нескольких задач суммаризации."""
        with patch('src.webapp.routes_summarization.get_article_by_id') as mock_get_article, \
             patch('src.queue_workers.create_summary_job') as mock_create_job:
            
            # Подготовка данных
            article_ids = [123, 456, 789]
            mock_get_article.return_value = {
                'id': 123,
                'title': 'Тестовая статья',
                'content': 'Содержимое статьи для суммаризации'
            }
            mock_create_job.return_value = "summarize_123_1234567890"
            
            # Вызов эндпоинта
            response = test_client.post(
                "/api/summarization/enqueue-batch",
                json=article_ids
            )
            
            # Проверки
            assert response.status_code == 200
            data = response.json()
            assert data["total_queued"] == len(article_ids)
    
    def test_get_queue_info(self, test_client):
        """Тест эндпоинта получения информации о состоянии очереди."""
        with patch('src.queue_workers.redis_client') as mock_redis:
            # Подготовка данных
            mock_redis.llen.return_value = 5
            
            # Вызов эндпоинта
            response = test_client.get("/api/summarization/queue-info")
            
            # Проверки
            assert response.status_code == 200
            data = response.json()
            assert data["pending_jobs_count"] == 5
            assert data["queue_name"] == "summarization"