"""Model settings routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from model_selection import apply_model_selection, current_available_models, update_override
from scheduler_agent.web import handlers as web_handlers

# 日本語: モデル設定API群 / English: Model settings router
router = APIRouter()


@router.get("/api/models", name="list_models")
def list_models():
    # 日本語: 利用可能モデルと現在選択を返す / English: Return available models and active selection
    return web_handlers.list_models(
        apply_model_selection_fn=apply_model_selection,
        current_available_models_fn=current_available_models,
    )


@router.post("/model_settings", name="update_model_settings")
async def update_model_settings(request: Request):
    # 日本語: セッション内上書き設定を更新 / English: Update in-memory model override settings
    return await web_handlers.update_model_settings(
        request,
        update_override_fn=update_override,
    )
