"""Chat routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from scheduler_agent.core.db import get_db

router = APIRouter()


@router.get("/api/flash", name="api_flash")
def api_flash(request: Request):
    import app as app_module

    return app_module.api_flash(request)


@router.api_route("/api/chat/history", methods=["GET", "DELETE"], name="manage_chat_history")
async def manage_chat_history(request: Request, db: Session = Depends(get_db)):
    import app as app_module

    return await app_module.manage_chat_history(request, db)


@router.post("/api/chat", name="chat")
async def chat(request: Request, db: Session = Depends(get_db)):
    import app as app_module

    return await app_module.chat(request, db)
