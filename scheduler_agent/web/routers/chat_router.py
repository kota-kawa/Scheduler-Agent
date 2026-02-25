"""Chat routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete
from sqlmodel import Session

from scheduler_agent.core.db import get_db
from scheduler_agent.services.chat_orchestration_service import process_chat_request
from scheduler_agent.services.reply_service import _extract_execution_trace_from_stored_content
from scheduler_agent.web import handlers as web_handlers
from scheduler_agent.web.templates import pop_flashed_messages

router = APIRouter()


@router.get("/api/flash", name="api_flash")
def api_flash(request: Request):
    return web_handlers.api_flash(request, pop_flashed_messages_fn=pop_flashed_messages)


@router.api_route("/api/chat/history", methods=["GET", "DELETE"], name="manage_chat_history")
async def manage_chat_history(request: Request, db: Session = Depends(get_db)):
    return await web_handlers.manage_chat_history(
        request,
        db,
        extract_execution_trace_fn=_extract_execution_trace_from_stored_content,
        delete_fn=delete,
    )


@router.post("/api/chat", name="chat")
async def chat(request: Request, db: Session = Depends(get_db)):
    return await web_handlers.chat(request, db, process_chat_request_fn=process_chat_request)
