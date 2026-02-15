"""Model settings routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/api/models", name="list_models")
def list_models():
    import app as app_module

    return app_module.list_models()


@router.post("/model_settings", name="update_model_settings")
async def update_model_settings(request: Request):
    import app as app_module

    return await app_module.update_model_settings(request)
