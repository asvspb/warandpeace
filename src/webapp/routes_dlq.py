
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional

from src.webapp import services

router = APIRouter()
templates = Jinja2Templates(directory="src/webapp/templates")

@router.get("/dlq", response_class=HTMLResponse)
async def list_dlq(request: Request, entity_type: Optional[str] = Query(None)):
    """Renders the Dead Letter Queue items."""
    items = services.get_dlq_items(entity_type=entity_type)
    return templates.TemplateResponse("dlq.html", {"request": request, "items": items, "entity_type": entity_type})
