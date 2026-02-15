"""Day detail API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from scheduler_agent.core.db import get_db

router = APIRouter()


@router.get("/api/day/{date_str}", name="api_day_view")
def api_day_view(date_str: str, db: Session = Depends(get_db)):
    import app as app_module

    return app_module.api_day_view(date_str, db)
