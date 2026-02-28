"""Page routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from scheduler_agent.core.db import get_db
from scheduler_agent.services.timeline_service import get_weekday_routines
from scheduler_agent.web import handlers as web_handlers
from scheduler_agent.web.templates import flash, template_response

# 日本語: HTMLページ配信用ルーター / English: Router for HTML page endpoints
router = APIRouter()


@router.get("/", response_class=HTMLResponse, name="index")
def index(request: Request, db: Session = Depends(get_db)):
    # 日本語: トップページ / English: Top page
    return web_handlers.index(request, template_response_fn=template_response)


@router.get("/agent-result", response_class=HTMLResponse, name="agent_result")
def agent_result(request: Request, db: Session = Depends(get_db)):
    # 日本語: エージェント結果ページ / English: Agent result page
    return web_handlers.agent_result(request, template_response_fn=template_response)


@router.api_route(
    "/agent-result/day/{date_str}", methods=["GET", "POST"], response_class=HTMLResponse, name="agent_day_view"
)
async def agent_day_view(request: Request, date_str: str, db: Session = Depends(get_db)):
    # 日本語: エージェント日次詳細ページ / English: Agent day-detail page
    return await web_handlers.agent_day_view(
        request,
        date_str,
        db,
        get_weekday_routines_fn=get_weekday_routines,
        flash_fn=flash,
        template_response_fn=template_response,
    )


@router.get("/embed/calendar", response_class=HTMLResponse, name="embed_calendar")
def embed_calendar(request: Request, db: Session = Depends(get_db)):
    # 日本語: 埋め込みカレンダーページ / English: Embedded calendar page
    return web_handlers.embed_calendar(request, template_response_fn=template_response)


@router.api_route("/day/{date_str}", methods=["GET", "POST"], response_class=HTMLResponse, name="day_view")
async def day_view(request: Request, date_str: str, db: Session = Depends(get_db)):
    # 日本語: 通常の日次詳細ページ / English: Standard day-detail page
    return await web_handlers.day_view(
        request,
        date_str,
        db,
        get_weekday_routines_fn=get_weekday_routines,
        flash_fn=flash,
        template_response_fn=template_response,
    )


@router.get("/routines", response_class=HTMLResponse, name="routines_list")
def routines_list(request: Request, db: Session = Depends(get_db)):
    # 日本語: ルーチン一覧ページ / English: Routine list page
    return web_handlers.routines_list(request, template_response_fn=template_response)


@router.get("/evaluation", response_class=HTMLResponse, name="evaluation_page")
def evaluation_page(request: Request):
    # 日本語: 評価ページ / English: Evaluation page
    return web_handlers.evaluation_page(request, template_response_fn=template_response)
