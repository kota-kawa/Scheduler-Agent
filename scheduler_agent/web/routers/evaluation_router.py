"""Evaluation routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete
from sqlmodel import Session

from scheduler_agent.core.db import get_db
from scheduler_agent.services.chat_orchestration_service import _run_scheduler_multi_step
from scheduler_agent.services.evaluation_seed_service import _seed_evaluation_data, seed_sample_data
from scheduler_agent.services.reply_service import _build_final_reply
from scheduler_agent.web import handlers as web_handlers

router = APIRouter()


@router.post("/api/evaluation/chat", name="evaluation_chat")
async def evaluation_chat(request: Request, db: Session = Depends(get_db)):
    return await web_handlers.evaluation_chat(
        request,
        db,
        run_scheduler_multi_step_fn=_run_scheduler_multi_step,
        build_final_reply_fn=_build_final_reply,
    )


@router.post("/api/evaluation/reset", name="evaluation_reset")
def evaluation_reset(db: Session = Depends(get_db)):
    return web_handlers.evaluation_reset(db, delete_fn=delete)


@router.post("/api/evaluation/seed", name="evaluation_seed")
async def evaluation_seed(request: Request, db: Session = Depends(get_db)):
    return await web_handlers.evaluation_seed(
        request,
        db,
        seed_evaluation_data_fn=_seed_evaluation_data,
    )


@router.post("/api/evaluation/seed_period", name="evaluation_seed_period")
async def evaluation_seed_period(request: Request, db: Session = Depends(get_db)):
    return await web_handlers.evaluation_seed_period(
        request,
        db,
        seed_evaluation_data_fn=_seed_evaluation_data,
    )


@router.post("/api/add_sample_data", name="add_sample_data")
def add_sample_data(db: Session = Depends(get_db)):
    return web_handlers.add_sample_data(db, seed_sample_data_fn=seed_sample_data)


@router.post("/api/evaluation/log", name="evaluation_log")
async def evaluation_log(request: Request, db: Session = Depends(get_db)):
    return await web_handlers.evaluation_log(request, db)


@router.get("/api/evaluation/history", name="evaluation_history")
def evaluation_history(db: Session = Depends(get_db)):
    return web_handlers.evaluation_history(db)
