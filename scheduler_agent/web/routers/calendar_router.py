"""Calendar API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from scheduler_agent.core.db import get_db

router = APIRouter()


@router.get("/api/calendar", name="api_calendar")
def api_calendar(request: Request, db: Session = Depends(get_db)):
    import app as app_module

    return app_module.api_calendar(request, db)
