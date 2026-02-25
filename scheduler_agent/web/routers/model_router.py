"""Model settings routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from model_selection import apply_model_selection, current_available_models, update_override
from scheduler_agent.web import handlers as web_handlers

router = APIRouter()


@router.get("/api/models", name="list_models")
def list_models():
    return web_handlers.list_models(
        apply_model_selection_fn=apply_model_selection,
        current_available_models_fn=current_available_models,
    )


@router.post("/model_settings", name="update_model_settings")
async def update_model_settings(request: Request):
    return await web_handlers.update_model_settings(
        request,
        update_override_fn=update_override,
    )
