"""Routine CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from scheduler_agent.core.db import get_db
from scheduler_agent.services.timeline_service import get_weekday_routines
from scheduler_agent.web import handlers as web_handlers

router = APIRouter()


@router.get("/api/routines/day/{weekday}", name="api_routines_by_day")
def api_routines_by_day(weekday: int, db: Session = Depends(get_db)):
    return web_handlers.api_routines_by_day(weekday, db, get_weekday_routines_fn=get_weekday_routines)


@router.get("/api/routines", name="api_routines")
def api_routines(db: Session = Depends(get_db)):
    return web_handlers.api_routines(db)


@router.post("/routines/add", name="add_routine")
async def add_routine(request: Request, db: Session = Depends(get_db)):
    return await web_handlers.add_routine(request, db)


@router.post("/routines/{id}/delete", name="delete_routine")
def delete_routine(request: Request, id: int, db: Session = Depends(get_db)):
    return web_handlers.delete_routine(request, id, db)


@router.post("/routines/{id}/step/add", name="add_step")
async def add_step(request: Request, id: int, db: Session = Depends(get_db)):
    return await web_handlers.add_step(request, id, db)


@router.post("/steps/{id}/delete", name="delete_step")
def delete_step(request: Request, id: int, db: Session = Depends(get_db)):
    return web_handlers.delete_step(request, id, db)
