"""Compatibility facade for Scheduler Agent.

This module keeps historical imports stable (`import app`) while delegating
business logic to the modular `scheduler_agent` package.
"""

from __future__ import annotations

import datetime
from typing import Any, Callable, Dict, Iterator, List, Union

from fastapi import Depends, Request
from sqlalchemy import delete
from sqlmodel import Session

from llm_client import UnifiedClient, _content_to_text, call_scheduler_llm
from model_selection import apply_model_selection, current_available_models, update_override
from scheduler_agent.asgi import app
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
import scheduler_agent.services.action_service as action_service_module
import scheduler_agent.services.chat_orchestration_service as chat_service_module
import scheduler_agent.services.evaluation_seed_service as eval_seed_service
import scheduler_agent.services.reply_service as reply_service_module
import scheduler_agent.services.schedule_parser_service as parser_service
import scheduler_agent.services.timeline_service as timeline_service_module
from scheduler_agent.web import handlers as web_handlers
from scheduler_agent.web.templates import flash, pop_flashed_messages, template_response

# 日本語: 環境変数変更後でも最新DB設定を反映する / English: Refresh DB engine to reflect late env overrides
refresh_engine_from_env()


# --- Service wrappers exposed for backward compatibility ---

# 日本語: 旧 `app` API 互換のため parser_service へ委譲 / English: Delegate to parser_service for legacy `app` API compatibility
def _parse_date(value: Any, default_date: datetime.date) -> datetime.date:
    return parser_service._parse_date(value, default_date)


def _resolve_schedule_expression(
    expression: Any,
    base_date: datetime.date,
    base_time: str = "00:00",
    default_time: str = "00:00",
) -> Dict[str, Any]:
    # 日本語: 日時解釈の本処理はサービス層を利用 / English: Use service-layer implementation for schedule resolution
    return parser_service._resolve_schedule_expression(expression, base_date, base_time, default_time)


def get_weekday_routines(db: Session, weekday_int: int) -> List[Routine]:
    # 日本語: 曜日別ルーチン取得を timeline_service に委譲 / English: Delegate weekday routine lookup to timeline_service
    return timeline_service_module.get_weekday_routines(db, weekday_int)


def _get_timeline_data(db: Session, date_obj: datetime.date):
    return timeline_service_module._get_timeline_data(db, date_obj)


def _build_scheduler_context(db: Session, today: datetime.date | None = None) -> str:
    # 日本語: LLM向けコンテキスト生成をサービス層で実行 / English: Build LLM context via service layer
    return timeline_service_module._build_scheduler_context(db, today)


def _apply_actions(db: Session, actions: List[Dict[str, Any]], default_date: datetime.date):
    # 日本語: ツールアクション適用の責務を action_service へ集約 / English: Centralize tool-action execution in action_service
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
    # 日本語: 最終返信整形は reply_service のロジックを再利用 / English: Reuse reply_service logic for final response formatting
    return reply_service_module._build_final_reply(
        user_message,
        reply_text,
        results,
        errors,
        summary_client_factory=UnifiedClient,
        content_to_text_fn=_content_to_text,
    )


def _run_scheduler_multi_step(
    db: Session,
    formatted_messages: List[Dict[str, str]],
    today: datetime.date,
    max_rounds: int | None = None,
) -> Dict[str, Any]:
    # 日本語: マルチラウンド実行エンジンを chat_service へ委譲 / English: Delegate multi-round orchestration to chat_service
    return chat_service_module._run_scheduler_multi_step(
        db,
        formatted_messages,
        today,
        max_rounds,
        call_scheduler_llm_fn=call_scheduler_llm,
        build_scheduler_context_fn=_build_scheduler_context,
        apply_actions_fn=_apply_actions,
    )


def process_chat_request(
    db: Session, message_or_history: Union[str, List[Dict[str, str]]], save_history: bool = True
) -> Dict[str, Any]:
    # 日本語: 互換APIとしてチャット処理を公開 / English: Expose chat processing through compatibility facade
    return chat_service_module.process_chat_request(
        db,
        message_or_history,
        save_history=save_history,
        run_scheduler_multi_step_fn=_run_scheduler_multi_step,
        build_final_reply_fn=_build_final_reply,
        attach_execution_trace_fn=_attach_execution_trace_to_stored_content,
    )


# --- Route logic wrappers (used by routers and direct tests) ---

# 日本語: テンプレート応答が必要なページ系ハンドラを共通化 / English: Common helper for template-based page handlers
def _template_page(
    handler: Callable[..., Any],
    request: Request,
):
    return handler(request, template_response_fn=template_response)


# 日本語: 日付ページ系ハンドラの依存注入を共通化 / English: Common dependency injection for date-page handlers
async def _date_page(
    handler: Callable[..., Any],
    request: Request,
    date_str: str,
    db: Session,
):
    return await handler(
        request,
        date_str,
        db,
        get_weekday_routines_fn=get_weekday_routines,
        flash_fn=flash,
        template_response_fn=template_response,
    )


# 日本語: 評価用シードAPIの呼び出しを共通化 / English: Common helper for evaluation seed endpoints
async def _evaluation_seed_endpoint(
    handler: Callable[..., Any],
    request: Request,
    db: Session,
):
    return await handler(
        request,
        db,
        seed_evaluation_data_fn=_seed_evaluation_data,
    )


# 日本語: 以下は Web ハンドラへの薄いパススルー層 / English: The wrappers below are thin pass-throughs to web handlers
def api_flash(request: Request):
    return web_handlers.api_flash(request, pop_flashed_messages_fn=pop_flashed_messages)


def api_calendar(request: Request, db: Session = Depends(get_db)):
    return web_handlers.api_calendar(request, db, get_weekday_routines_fn=get_weekday_routines)


def index(request: Request, db: Session = Depends(get_db)):
    return _template_page(web_handlers.index, request)


def agent_result(request: Request, db: Session = Depends(get_db)):
    return _template_page(web_handlers.agent_result, request)


async def agent_day_view(request: Request, date_str: str, db: Session = Depends(get_db)):
    return await _date_page(web_handlers.agent_day_view, request, date_str, db)


def embed_calendar(request: Request, db: Session = Depends(get_db)):
    return _template_page(web_handlers.embed_calendar, request)


def api_day_view(date_str: str, db: Session = Depends(get_db)):
    return web_handlers.api_day_view(date_str, db, get_timeline_data_fn=_get_timeline_data)


async def day_view(request: Request, date_str: str, db: Session = Depends(get_db)):
    return await _date_page(web_handlers.day_view, request, date_str, db)


def api_routines_by_day(weekday: int, db: Session = Depends(get_db)):
    return web_handlers.api_routines_by_day(weekday, db, get_weekday_routines_fn=get_weekday_routines)


def api_routines(db: Session = Depends(get_db)):
    return web_handlers.api_routines(db)


def routines_list(request: Request, db: Session = Depends(get_db)):
    return _template_page(web_handlers.routines_list, request)


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
    # 日本語: 履歴取得/削除時に execution trace の抽出器を注入 / English: Inject execution-trace extractor for history endpoints
    return await web_handlers.manage_chat_history(
        request,
        db,
        extract_execution_trace_fn=_extract_execution_trace_from_stored_content,
        delete_fn=delete,
    )


async def chat(request: Request, db: Session = Depends(get_db)):
    # 日本語: チャットAPIは process_chat_request ラッパー経由で実行 / English: Route chat API through process_chat_request wrapper
    return await web_handlers.chat(request, db, process_chat_request_fn=process_chat_request)


def evaluation_page(request: Request):
    return _template_page(web_handlers.evaluation_page, request)


async def evaluation_chat(request: Request, db: Session = Depends(get_db)):
    return await web_handlers.evaluation_chat(
        request,
        db,
        run_scheduler_multi_step_fn=_run_scheduler_multi_step,
        build_final_reply_fn=_build_final_reply,
    )


def evaluation_reset(db: Session = Depends(get_db)):
    # 日本語: 評価データ初期化時に SQLAlchemy delete を注入 / English: Inject SQLAlchemy delete for evaluation reset
    return web_handlers.evaluation_reset(db, delete_fn=delete)


def _seed_evaluation_data(db: Session, start_date: datetime.date, end_date: datetime.date):
    # 日本語: 互換エクスポート用のシード関数 / English: Compatibility export for evaluation seed helper
    return eval_seed_service._seed_evaluation_data(db, start_date, end_date)


async def evaluation_seed(request: Request, db: Session = Depends(get_db)):
    return await _evaluation_seed_endpoint(web_handlers.evaluation_seed, request, db)


async def evaluation_seed_period(request: Request, db: Session = Depends(get_db)):
    return await _evaluation_seed_endpoint(web_handlers.evaluation_seed_period, request, db)


def add_sample_data(db: Session = Depends(get_db)):
    return web_handlers.add_sample_data(db, seed_sample_data_fn=eval_seed_service.seed_sample_data)


async def evaluation_log(request: Request, db: Session = Depends(get_db)):
    return await web_handlers.evaluation_log(request, db)


def evaluation_history(db: Session = Depends(get_db)):
    return web_handlers.evaluation_history(db)


_MODEL_EXPORTS = [
    "Session",
    "Iterator",
    "Routine",
    "Step",
    "DailyLog",
    "CustomTask",
    "DayLog",
    "ChatHistory",
    "EvaluationResult",
]

_DB_EXPORTS = [
    "create_session",
    "get_db",
    "engine",
    "_ensure_db_initialized",
    "_init_db",
]

_SERVICE_EXPORTS = [
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
    "_seed_evaluation_data",
]

_ROUTE_EXPORTS = [
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
    "add_sample_data",
    "evaluation_log",
    "evaluation_history",
]

__all__ = [
    "app",
    *_MODEL_EXPORTS,
    *_DB_EXPORTS,
    *_SERVICE_EXPORTS,
    *_ROUTE_EXPORTS,
]
