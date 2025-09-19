
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional

from src.webapp import services

router = APIRouter()
import os as _os
_BASE_DIR = _os.path.dirname(_os.path.abspath(__file__))
_TEMPLATES_DIR = _os.path.join(_BASE_DIR, "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

@router.get("/dlq", response_class=HTMLResponse)
async def list_dlq(request: Request, entity_type: Optional[str] = Query(None)):
    """Renders the Dead Letter Queue items."""
    items = services.get_dlq_items(entity_type=entity_type)
    return templates.TemplateResponse("dlq.html", {"request": request, "items": items, "entity_type": entity_type})
