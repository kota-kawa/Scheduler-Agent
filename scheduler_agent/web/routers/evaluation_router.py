"""Evaluation routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from scheduler_agent.core.db import get_db

router = APIRouter()


@router.post("/api/evaluation/chat", name="evaluation_chat")
async def evaluation_chat(request: Request, db: Session = Depends(get_db)):
    import app as app_module

    return await app_module.evaluation_chat(request, db)


@router.post("/api/evaluation/reset", name="evaluation_reset")
def evaluation_reset(db: Session = Depends(get_db)):
    import app as app_module

    return app_module.evaluation_reset(db)


@router.post("/api/evaluation/seed", name="evaluation_seed")
async def evaluation_seed(request: Request, db: Session = Depends(get_db)):
    import app as app_module

    return await app_module.evaluation_seed(request, db)


@router.post("/api/evaluation/seed_period", name="evaluation_seed_period")
async def evaluation_seed_period(request: Request, db: Session = Depends(get_db)):
    import app as app_module

    return await app_module.evaluation_seed_period(request, db)


@router.post("/api/add_sample_data", name="add_sample_data")
def add_sample_data(db: Session = Depends(get_db)):
    import app as app_module

    return app_module.add_sample_data(db)


@router.post("/api/evaluation/log", name="evaluation_log")
async def evaluation_log(request: Request, db: Session = Depends(get_db)):
    import app as app_module

    return await app_module.evaluation_log(request, db)


@router.get("/api/evaluation/history", name="evaluation_history")
def evaluation_history(db: Session = Depends(get_db)):
    import app as app_module

    return app_module.evaluation_history(db)
