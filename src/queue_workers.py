"""
Фоновые воркеры для обработки задач суммаризации с использованием Redis Queue.
"""
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

import redis
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

from src.summarizer import summarize_text_background
from src.models import Summary, SummaryStatus, Article
from src.database import get_db_connection, init_db
from src import config

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Подключение к Redis
redis_client = None
redis_url = getattr(config, 'REDIS_URL', None)
if redis_url:
    redis_client = redis.from_url(redis_url)
else:
    redis_url = "redis://localhost:6379/0"
    redis_client = redis.from_url(redis_url)

# Имя очереди для задач суммаризации
SUMMARY_QUEUE_NAME = "summarization"

def create_summary_job(article_id: int, article_title: str, article_content: str) -> str:
    """
    Создает задачу суммаризации в очереди и возвращает ID задачи.
    
    Args:
        article_id: ID статьи в базе данных
        article_title: Заголовок статьи
        article_content: Текст статьи для суммаризации
    
    Returns:
        str: ID задачи в очереди
    """
    job_data = {
        "article_id": article_id,
        "title": article_title,
        "content": article_content,
        "created_at": datetime.utcnow().isoformat()
    }
    
    # Помещаем задачу в очередь Redis
    job_id = f"summarize_{article_id}_{int(datetime.utcnow().timestamp())}"
    redis_client.lpush(SUMMARY_QUEUE_NAME, json.dumps(job_data))
    
    logger.info(f"Создана задача суммаризации для статьи {article_id}, ID задачи: {job_id}")
    
    # Обновляем статус суммаризации в базе данных на PENDING
    update_summary_status(article_id, SummaryStatus.PENDING)
    
    return job_id

def process_summary_job(job_data: Dict[str, Any]) -> bool:
    """
    Обрабатывает задачу суммаризации.
    
    Args:
        job_data: Данные задачи с информацией о статье
    
    Returns:
        bool: True если обработка прошла успешно, False в случае ошибки
    """
    try:
        article_id = job_data["article_id"]
        content = job_data["content"]
        
        logger.info(f"Начинаю обработку задачи суммаризации для статьи {article_id}")
        
        # Выполняем суммаризацию текста
        summary_text = summarize_text_background(content, article_id)
        
        if summary_text is None:
            logger.error(f"Не удалось получить суммаризацию для статьи {article_id}")
            update_summary_status(article_id, SummaryStatus.FAILED)
            return False
        
        # Сохраняем результат суммаризации в базе данных
        save_summary_result(article_id, summary_text)
        
        logger.info(f"Суммаризация для статьи {article_id} успешно завершена")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при обработке задачи суммаризации: {e}", exc_info=True)
        try:
            article_id = job_data.get("article_id")
            if article_id:
                update_summary_status(article_id, SummaryStatus.FAILED)
        except Exception:
            pass
        return False

def update_summary_status(article_id: int, status: SummaryStatus) -> None:
    """
    Обновляет статус суммаризации для статьи в базе данных.
    
    Args:
        article_id: ID статьи
        status: Новый статус
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Проверяем, существует ли уже запись в таблице summaries для этой статьи
            cursor.execute(
                "SELECT id FROM summaries WHERE article_id = ? LIMIT 1",
                (article_id,)
            )
            existing_summary = cursor.fetchone()
            
            if existing_summary:
                # Обновляем существующую запись
                cursor.execute(
                    "UPDATE summaries SET status = ? WHERE article_id = ?",
                    (status.value, article_id)
                )
            else:
                # Создаем новую запись в таблице summaries
                cursor.execute(
                    "INSERT INTO summaries (article_id, summary_text, status, created_at) VALUES (?, ?, ?, ?)",
                    (article_id, "", status.value, datetime.utcnow().isoformat())
                )
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка при обновлении статуса суммаризации для статьи {article_id}: {e}")

def save_summary_result(article_id: int, summary_text: str) -> None:
    """
    Сохраняет результат суммаризации в базе данных.
    
    Args:
        article_id: ID статьи
        summary_text: Текст суммаризации
    """
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Обновляем статус на OK и записываем текст суммаризации
            cursor.execute(
                "UPDATE summaries SET summary_text = ?, status = ? WHERE article_id = ?",
                (summary_text, SummaryStatus.OK.value, article_id)
            )
            # Также обновляем поле summary_text в таблице articles для совместимости
            cursor.execute(
                "UPDATE articles SET summary_text = ? WHERE id = ?",
                (summary_text, article_id)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Ошибка при сохранении результата суммаризации для статьи {article_id}: {e}")

def get_job_status(job_id: str) -> Dict[str, Any]:
    """
    Получает статус задачи по её ID.
    
    Args:
        job_id: ID задачи
    
    Returns:
        Dict с информацией о статусе задачи
    """
    # В простой реализации с Redis списками мы не можем напрямую получить статус задачи по ID
    # Вместо этого, мы можем получить статус из базы данных по article_id
    # Извлекаем article_id из job_id (формат: summarize_{article_id}_{timestamp})
    try:
        parts = job_id.split('_')
        if len(parts) >= 3 and parts[0] == 'summarize':
            article_id = int(parts[1])
            
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT status FROM summaries WHERE article_id = ? LIMIT 1",
                    (article_id,)
                )
                row = cursor.fetchone()
                
                if row:
                    status = row[0]
                    return {
                        "job_id": job_id,
                        "article_id": article_id,
                        "status": status,
                        "completed": status == SummaryStatus.OK.value
                    }
                
                # Если записи нет, задача может быть в очереди
                return {
                    "job_id": job_id,
                    "article_id": article_id,
                    "status": SummaryStatus.PENDING.value,
                    "completed": False
                }
    except Exception as e:
        logger.error(f"Ошибка при получении статуса задачи {job_id}: {e}")
        return {
            "job_id": job_id,
            "status": "unknown",
            "completed": False
        }

def worker_loop():
    """
    Основной цикл воркера, который обрабатывает задачи из очереди.
    """
    logger.info("Запуск воркера суммаризации...")
    
    while True:
        try:
            # Получаем задачу из очереди (с ожиданием)
            result = redis_client.brpop(SUMMARY_QUEUE_NAME, timeout=5)
            
            if result is None:
                # Таймаут, продолжаем цикл
                continue
            
            # Результат - кортеж (имя_ключа, данные)
            _, job_data_str = result
            job_data = json.loads(job_data_str)
            
            # Обрабатываем задачу
            success = process_summary_job(job_data)
            
            if not success:
                logger.error(f"Ошибка обработки задачи: {job_data}")
            
        except KeyboardInterrupt:
            logger.info("Остановка воркера по сигналу...")
            break
        except Exception as e:
            logger.error(f"Ошибка в цикле воркера: {e}", exc_info=True)
            # Делаем паузу перед следующей итерацией, чтобы не перегружать логи
            import time
            time.sleep(1)

if __name__ == "__main__":
    # При запуске как скрипт, запускаем воркер
    worker_loop()