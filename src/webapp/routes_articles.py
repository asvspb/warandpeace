
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import math

from src.webapp import services

router = APIRouter()
templates = Jinja2Templates(directory="src/webapp/templates")

@router.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Renders the main dashboard page."""
    stats = services.get_dashboard_stats()
    return templates.TemplateResponse("index.html", {"request": request, "stats": stats})

@router.get("/articles", response_class=HTMLResponse)
async def list_articles(
    request: Request,
    page: int = 1,
    page_size: int = Query(50, ge=1, le=200),
    q: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    has_content: int = Query(1, ge=0, le=1),
):
    """Renders the list of articles with pagination and filters."""
    articles, total_articles = services.get_articles(page, page_size, q, start_date, end_date, has_content)
    total_pages = math.ceil(total_articles / page_size)
    
    return templates.TemplateResponse(
        "articles_list.html",
        {
            "request": request,
            "articles": articles,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "total_articles": total_articles,
            "q": q,
            "start_date": start_date,
            "end_date": end_date,
            "has_content": has_content,
        },
    )

@router.get("/articles/{article_id}", response_class=HTMLResponse)
async def read_article(
    request: Request, 
    article_id: int
):
    """Renders the detail page for a single article."""
    article = services.get_article_by_id(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return templates.TemplateResponse("article_detail.html", {"request": request, "article": article})
