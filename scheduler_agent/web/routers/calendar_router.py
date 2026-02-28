"""Calendar API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from scheduler_agent.core.db import get_db
from scheduler_agent.services.timeline_service import get_weekday_routines
from scheduler_agent.web import handlers as web_handlers

# 日本語: カレンダーAPI群 / English: Calendar API router
router = APIRouter()


@router.get("/api/calendar", name="api_calendar")
def api_calendar(request: Request, db: Session = Depends(get_db)):
    # 日本語: 月間カレンダー集計を handler に委譲 / English: Delegate monthly calendar aggregation to handler
    return web_handlers.api_calendar(request, db, get_weekday_routines_fn=get_weekday_routines)
