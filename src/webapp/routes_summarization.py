"""
API-эндпоинты для управления очередью задач суммаризации.
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any, Optional

from src.queue_workers import create_summary_job, get_job_status
from src.webapp.services import get_article_by_id

router = APIRouter(prefix="/api/summarization")

@router.post("/enqueue")
async def enqueue_summarization(article_id: int) -> Dict[str, Any]:
    """
    Добавляет задачу суммаризации статьи в очередь.
    
    Args:
        article_id: ID статьи для суммаризации
    
    Returns:
        Dict с ID задачи и информацией о ней
    """
    # Получаем статью из базы данных
    article = get_article_by_id(article_id)
    if not article:
        raise HTTPException(status_code=404, detail=f"Article with ID {article_id} not found")
    
    # Проверяем, есть ли контент для суммаризации
    content = article.get('content') or article.get('summary_text')
    if not content:
        raise HTTPException(status_code=400, detail=f"Article with ID {article_id} has no content to summarize")
    
    # Создаем задачу в очереди
    job_id = create_summary_job(
        article_id=article_id,
        article_title=article.get('title', ''),
        article_content=content
    )
    
    return {
        "job_id": job_id,
        "article_id": article_id,
        "status": "queued",
        "message": f"Summarization job for article {article_id} has been queued"
    }

@router.get("/status/{job_id}")
async def get_summarization_status(job_id: str) -> Dict[str, Any]:
    """
    Возвращает статус задачи суммаризации по ID.
    
    Args:
        job_id: ID задачи
    
    Returns:
        Dict с информацией о статусе задачи
    """
    status_info = get_job_status(job_id)
    
    if not status_info or status_info.get("status") == "unknown":
        raise HTTPException(status_code=404, detail=f"Job with ID {job_id} not found")
    
    return status_info

@router.post("/enqueue-batch")
async def enqueue_summarization_batch(article_ids: list[int]) -> Dict[str, Any]:
    """
    Добавляет несколько задач суммаризации в очередь.
    
    Args:
        article_ids: Список ID статей для суммаризации
    
    Returns:
        Dict с информацией о созданных задачах
    """
    results = []
    errors = []
    
    for article_id in article_ids:
        try:
            # Получаем статью из базы данных
            article = get_article_by_id(article_id)
            if not article:
                errors.append(f"Article with ID {article_id} not found")
                continue
            
            # Проверяем, есть ли контент для суммаризации
            content = article.get('content') or article.get('summary_text')
            if not content:
                errors.append(f"Article with ID {article_id} has no content to summarize")
                continue
            
            # Создаем задачу в очереди
            job_id = create_summary_job(
                article_id=article_id,
                article_title=article.get('title', ''),
                article_content=content
            )
            
            results.append({
                "article_id": article_id,
                "job_id": job_id,
                "status": "queued"
            })
        except Exception as e:
            errors.append(f"Error processing article {article_id}: {str(e)}")
    
    return {
        "queued_jobs": results,
        "errors": errors,
        "total_queued": len(results),
        "total_errors": len(errors)
    }

@router.get("/queue-info")
async def get_queue_info() -> Dict[str, Any]:
    """
    Возвращает информацию о состоянии очереди задач.
    
    Returns:
        Dict с информацией о количестве задач в очереди
    """
    from src.queue_workers import redis_client, SUMMARY_QUEUE_NAME
    
    try:
        queue_length = redis_client.llen(SUMMARY_QUEUE_NAME)
        return {
            "queue_name": SUMMARY_QUEUE_NAME,
            "pending_jobs_count": queue_length,
            "timestamp": __import__('datetime').datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting queue info: {str(e)}")