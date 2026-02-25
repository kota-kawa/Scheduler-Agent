"""Day detail API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from scheduler_agent.core.db import get_db
from scheduler_agent.services.timeline_service import _get_timeline_data
from scheduler_agent.web import handlers as web_handlers

router = APIRouter()


@router.get("/api/day/{date_str}", name="api_day_view")
def api_day_view(date_str: str, db: Session = Depends(get_db)):
    return web_handlers.api_day_view(date_str, db, get_timeline_data_fn=_get_timeline_data)
