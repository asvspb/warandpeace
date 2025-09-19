
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.webapp import services

router = APIRouter()
import os as _os
_BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
_TEMPLATES_DIR = _os.path.join(_BASE_DIR, "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

@router.get("/duplicates", response_class=HTMLResponse)
async def list_duplicate_groups(request: Request):
    """Renders the list of duplicate groups based on content hash."""
    groups = services.get_duplicate_groups()
    return templates.TemplateResponse("duplicates.html", {"request": request, "groups": groups})

@router.get("/duplicates/{content_hash}", response_class=HTMLResponse)
async def list_articles_for_hash(request: Request, content_hash: str):
    """Renders the list of articles for a specific content hash."""
    articles = services.get_articles_by_hash(content_hash)
    if not articles:
        raise HTTPException(status_code=404, detail="No articles found for this hash")
    return templates.TemplateResponse(
        "duplicate_articles.html",
        {"request": request, "articles": articles, "hash": content_hash}
    )
