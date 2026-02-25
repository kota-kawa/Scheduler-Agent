"""Compatibility facade for Scheduler Agent.

This module keeps historical imports stable (`import app`) while delegating
business logic to the modular `scheduler_agent` package.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Iterator, List, Union

from fastapi import Depends, Request
from sqlalchemy import delete
from sqlmodel import Session

from llm_client import UnifiedClient, _content_to_text, call_scheduler_llm
from model_selection import apply_model_selection, current_available_models, update_override
from scheduler_agent.application import app
from scheduler_agent.core.db import (
    _ensure_db_initialized,
    _init_db,
    create_session,
    engine,
    get_db,
    refresh_engine_from_env,
)
from scheduler_agent.models import (
    ChatHistory,
    CustomTask,
    DailyLog,
    DayLog,
    EvaluationResult,
    Routine,
    Step,
)
from scheduler_agent.services import action_service as action_service_module
from scheduler_agent.services import chat_orchestration_service as chat_service_module
from scheduler_agent.services import evaluation_seed_service as eval_seed_service
from scheduler_agent.services import reply_service as reply_service_module
from scheduler_agent.services import schedule_parser_service as parser_service
from scheduler_agent.services import timeline_service as timeline_service_module
from scheduler_agent.web import handlers as web_handlers
from scheduler_agent.web.templates import flash, pop_flashed_messages, template_response

refresh_engine_from_env()


# --- Service wrappers exposed for backward compatibility ---

def _parse_date(value: Any, default_date: datetime.date) -> datetime.date:
    return parser_service._parse_date(value, default_date)


def _resolve_schedule_expression(
    expression: Any,
    base_date: datetime.date,
    base_time: str = "00:00",
    default_time: str = "00:00",
) -> Dict[str, Any]:
    return parser_service._resolve_schedule_expression(expression, base_date, base_time, default_time)


def get_weekday_routines(db: Session, weekday_int: int) -> List[Routine]:
    return timeline_service_module.get_weekday_routines(db, weekday_int)


def _get_timeline_data(db: Session, date_obj: datetime.date):
    return timeline_service_module._get_timeline_data(db, date_obj)


def _build_scheduler_context(db: Session, today: datetime.date | None = None) -> str:
    return timeline_service_module._build_scheduler_context(db, today)


def _apply_actions(db: Session, actions: List[Dict[str, Any]], default_date: datetime.date):
    return action_service_module._apply_actions(db, actions, default_date)


def _attach_execution_trace_to_stored_content(
    content: str,
    execution_trace: List[Dict[str, Any]] | None,
) -> str:
    return reply_service_module._attach_execution_trace_to_stored_content(content, execution_trace)


def _extract_execution_trace_from_stored_content(content: Any) -> tuple[str, List[Dict[str, Any]]]:
    return reply_service_module._extract_execution_trace_from_stored_content(content)


def _build_final_reply(
    user_message: str,
    reply_text: str,
    results: List[str],
    errors: List[str],
) -> str:
    # Keep monkeypatch compatibility in tests (`app.UnifiedClient`).
    reply_service_module.UnifiedClient = UnifiedClient
    reply_service_module._content_to_text = _content_to_text
    return reply_service_module._build_final_reply(user_message, reply_text, results, errors)


def _run_scheduler_multi_step(
    db: Session,
    formatted_messages: List[Dict[str, str]],
    today: datetime.date,
    max_rounds: int | None = None,
) -> Dict[str, Any]:
    # Keep monkeypatch compatibility in tests (`app.call_scheduler_llm`, etc).
    chat_service_module.call_scheduler_llm = call_scheduler_llm
    chat_service_module._build_scheduler_context = _build_scheduler_context
    chat_service_module._apply_actions = _apply_actions
    return chat_service_module._run_scheduler_multi_step(db, formatted_messages, today, max_rounds)


def process_chat_request(
    db: Session, message_or_history: Union[str, List[Dict[str, str]]], save_history: bool = True
) -> Dict[str, Any]:
    formatted_messages = []
    user_message = ""

    if isinstance(message_or_history, str):
        user_message = message_or_history
        formatted_messages = [{"role": "user", "content": user_message}]
    else:
        formatted_messages = message_or_history
        if formatted_messages and formatted_messages[-1].get("role") == "user":
            user_message = formatted_messages[-1].get("content", "")
        else:
            user_message = "(Context only)"

    if save_history:
        try:
            db.add(ChatHistory(role="user", content=user_message))
            db.commit()
        except Exception as exc:
            db.rollback()
            print(f"Failed to save user message: {exc}")

    today = datetime.date.today()
    execution = _run_scheduler_multi_step(db, formatted_messages, today)
    final_reply = _build_final_reply(
        user_message=user_message,
        reply_text=execution.get("reply_text", ""),
        results=execution.get("results", []),
        errors=execution.get("errors", []),
    )

    if save_history:
        try:
            stored_assistant_content = _attach_execution_trace_to_stored_content(
                final_reply,
                execution.get("execution_trace", []),
            )
            db.add(ChatHistory(role="assistant", content=stored_assistant_content))
            db.commit()
        except Exception as exc:
            db.rollback()
            print(f"Failed to save assistant message: {exc}")

    results = execution.get("results", [])
    return {
        "reply": final_reply,
        "should_refresh": (len(results) > 0),
        "modified_ids": execution.get("modified_ids", []),
        "execution_trace": execution.get("execution_trace", []),
    }


# --- Route logic wrappers (used by routers and direct tests) ---

def api_flash(request: Request):
    return web_handlers.api_flash(request, pop_flashed_messages_fn=pop_flashed_messages)


def api_calendar(request: Request, db: Session = Depends(get_db)):
    return web_handlers.api_calendar(request, db, get_weekday_routines_fn=get_weekday_routines)


def index(request: Request, db: Session = Depends(get_db)):
    return web_handlers.index(request, template_response_fn=template_response)


def agent_result(request: Request, db: Session = Depends(get_db)):
    return web_handlers.agent_result(request, template_response_fn=template_response)


async def agent_day_view(request: Request, date_str: str, db: Session = Depends(get_db)):
    return await web_handlers.agent_day_view(
        request,
        date_str,
        db,
        get_weekday_routines_fn=get_weekday_routines,
        flash_fn=flash,
        template_response_fn=template_response,
    )


def embed_calendar(request: Request, db: Session = Depends(get_db)):
    return web_handlers.embed_calendar(request, template_response_fn=template_response)


def api_day_view(date_str: str, db: Session = Depends(get_db)):
    return web_handlers.api_day_view(date_str, db, get_timeline_data_fn=_get_timeline_data)


async def day_view(request: Request, date_str: str, db: Session = Depends(get_db)):
    return await web_handlers.day_view(
        request,
        date_str,
        db,
        get_weekday_routines_fn=get_weekday_routines,
        flash_fn=flash,
        template_response_fn=template_response,
    )


def api_routines_by_day(weekday: int, db: Session = Depends(get_db)):
    return web_handlers.api_routines_by_day(weekday, db, get_weekday_routines_fn=get_weekday_routines)


def api_routines(db: Session = Depends(get_db)):
    return web_handlers.api_routines(db)


def routines_list(request: Request, db: Session = Depends(get_db)):
    return web_handlers.routines_list(request, template_response_fn=template_response)


async def add_routine(request: Request, db: Session = Depends(get_db)):
    return await web_handlers.add_routine(request, db)


def delete_routine(request: Request, id: int, db: Session = Depends(get_db)):
    return web_handlers.delete_routine(request, id, db)


async def add_step(request: Request, id: int, db: Session = Depends(get_db)):
    return await web_handlers.add_step(request, id, db)


def delete_step(request: Request, id: int, db: Session = Depends(get_db)):
    return web_handlers.delete_step(request, id, db)


def list_models():
    return web_handlers.list_models(
        apply_model_selection_fn=apply_model_selection,
        current_available_models_fn=current_available_models,
    )


async def update_model_settings(request: Request):
    return await web_handlers.update_model_settings(
        request,
        update_override_fn=update_override,
    )


async def manage_chat_history(request: Request, db: Session = Depends(get_db)):
    return await web_handlers.manage_chat_history(
        request,
        db,
        extract_execution_trace_fn=_extract_execution_trace_from_stored_content,
        delete_fn=delete,
    )


async def chat(request: Request, db: Session = Depends(get_db)):
    return await web_handlers.chat(request, db, process_chat_request_fn=process_chat_request)


def evaluation_page(request: Request):
    return web_handlers.evaluation_page(request, template_response_fn=template_response)


async def evaluation_chat(request: Request, db: Session = Depends(get_db)):
    return await web_handlers.evaluation_chat(
        request,
        db,
        run_scheduler_multi_step_fn=_run_scheduler_multi_step,
        build_final_reply_fn=_build_final_reply,
    )


def evaluation_reset(db: Session = Depends(get_db)):
    return web_handlers.evaluation_reset(db, delete_fn=delete)


async def evaluation_seed(request: Request, db: Session = Depends(get_db)):
    return await web_handlers.evaluation_seed(
        request,
        db,
        seed_evaluation_data_fn=_seed_evaluation_data,
    )


async def evaluation_seed_period(request: Request, db: Session = Depends(get_db)):
    return await web_handlers.evaluation_seed_period(
        request,
        db,
        seed_evaluation_data_fn=_seed_evaluation_data,
    )


def _seed_evaluation_data(db: Session, start_date: datetime.date, end_date: datetime.date):
    return eval_seed_service._seed_evaluation_data(db, start_date, end_date)


def add_sample_data(db: Session = Depends(get_db)):
    return web_handlers.add_sample_data(db, seed_sample_data_fn=eval_seed_service.seed_sample_data)


async def evaluation_log(request: Request, db: Session = Depends(get_db)):
    return await web_handlers.evaluation_log(request, db)


def evaluation_history(db: Session = Depends(get_db)):
    return web_handlers.evaluation_history(db)


__all__ = [
    "app",
    "Session",
    "Iterator",
    "Routine",
    "Step",
    "DailyLog",
    "CustomTask",
    "DayLog",
    "ChatHistory",
    "EvaluationResult",
    "create_session",
    "get_db",
    "engine",
    "_ensure_db_initialized",
    "_init_db",
    "get_weekday_routines",
    "_resolve_schedule_expression",
    "_build_scheduler_context",
    "_get_timeline_data",
    "_apply_actions",
    "_run_scheduler_multi_step",
    "_attach_execution_trace_to_stored_content",
    "_extract_execution_trace_from_stored_content",
    "_build_final_reply",
    "process_chat_request",
    "api_flash",
    "api_calendar",
    "index",
    "agent_result",
    "agent_day_view",
    "embed_calendar",
    "api_day_view",
    "day_view",
    "api_routines_by_day",
    "api_routines",
    "routines_list",
    "add_routine",
    "delete_routine",
    "add_step",
    "delete_step",
    "list_models",
    "update_model_settings",
    "manage_chat_history",
    "chat",
    "evaluation_page",
    "evaluation_chat",
    "evaluation_reset",
    "evaluation_seed",
    "evaluation_seed_period",
    "_seed_evaluation_data",
    "add_sample_data",
    "evaluation_log",
    "evaluation_history",
]
