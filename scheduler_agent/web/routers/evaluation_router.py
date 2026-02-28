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

# 日本語: 評価機能API群 / English: Evaluation feature router
router = APIRouter()


@router.post("/api/evaluation/chat", name="evaluation_chat")
async def evaluation_chat(request: Request, db: Session = Depends(get_db)):
    # 日本語: 評価用チャットを実行 / English: Execute evaluation chat flow
    return await web_handlers.evaluation_chat(
        request,
        db,
        run_scheduler_multi_step_fn=_run_scheduler_multi_step,
        build_final_reply_fn=_build_final_reply,
    )


@router.post("/api/evaluation/reset", name="evaluation_reset")
def evaluation_reset(db: Session = Depends(get_db)):
    # 日本語: 評価用データをリセット / English: Reset evaluation data
    return web_handlers.evaluation_reset(db, delete_fn=delete)


@router.post("/api/evaluation/seed", name="evaluation_seed")
async def evaluation_seed(request: Request, db: Session = Depends(get_db)):
    # 日本語: 単日シード投入 / English: Seed one-day evaluation fixtures
    return await web_handlers.evaluation_seed(
        request,
        db,
        seed_evaluation_data_fn=_seed_evaluation_data,
    )


@router.post("/api/evaluation/seed_period", name="evaluation_seed_period")
async def evaluation_seed_period(request: Request, db: Session = Depends(get_db)):
    # 日本語: 期間シード投入 / English: Seed range-based evaluation fixtures
    return await web_handlers.evaluation_seed_period(
        request,
        db,
        seed_evaluation_data_fn=_seed_evaluation_data,
    )


@router.post("/api/add_sample_data", name="add_sample_data")
def add_sample_data(db: Session = Depends(get_db)):
    # 日本語: 手動確認用サンプルデータ投入 / English: Seed sample data for manual checks
    return web_handlers.add_sample_data(db, seed_sample_data_fn=seed_sample_data)


@router.post("/api/evaluation/log", name="evaluation_log")
async def evaluation_log(request: Request, db: Session = Depends(get_db)):
    # 日本語: 評価結果ログ登録 / English: Persist evaluation run log
    return await web_handlers.evaluation_log(request, db)


@router.get("/api/evaluation/history", name="evaluation_history")
def evaluation_history(db: Session = Depends(get_db)):
    # 日本語: 評価履歴取得 / English: Fetch evaluation history list
    return web_handlers.evaluation_history(db)
