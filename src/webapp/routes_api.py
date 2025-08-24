
from fastapi import APIRouter, Depends, Query
from typing import Optional, List, Dict, Any

from src.webapp import services
from src.backfill import get_status as backfill_get_status

router = APIRouter(prefix="/api")

@router.get("/articles", response_model=List[Dict[str, Any]])
async def api_list_articles(
    page: int = 1,
    page_size: int = Query(50, ge=1, le=200),
    q: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    """API endpoint to get a paginated list of articles."""
    articles, _ = services.get_articles(page, page_size, q, start_date, end_date)
    return articles

@router.get("/articles/{article_id}", response_model=Dict[str, Any])
async def api_read_article(article_id: int):
    """API endpoint to get a single article by ID."""
    article = services.get_article_by_id(article_id)
    if not article:
        return {"error": "Article not found"}
    return article


@router.get("/admin/stats")
async def api_admin_session_stats() -> Dict[str, Any]:
    """Admin JSON endpoint returning current session stats.

    Note: Global auth middleware in server.py protects /api when enabled and key is configured.
    """
    return services.get_session_stats()


@router.get("/backfill/status")
async def api_backfill_status() -> Dict[str, Any]:
    """Public API (protected by API key when enabled) for backfill progress."""
    return backfill_get_status()
