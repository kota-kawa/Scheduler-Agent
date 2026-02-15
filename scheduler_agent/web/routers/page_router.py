"""Page routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from scheduler_agent.core.db import get_db

router = APIRouter()


@router.get("/", response_class=HTMLResponse, name="index")
def index(request: Request, db: Session = Depends(get_db)):
    import app as app_module

    return app_module.index(request, db)


@router.get("/agent-result", response_class=HTMLResponse, name="agent_result")
def agent_result(request: Request, db: Session = Depends(get_db)):
    import app as app_module

    return app_module.agent_result(request, db)


@router.api_route(
    "/agent-result/day/{date_str}", methods=["GET", "POST"], response_class=HTMLResponse, name="agent_day_view"
)
async def agent_day_view(request: Request, date_str: str, db: Session = Depends(get_db)):
    import app as app_module

    return await app_module.agent_day_view(request, date_str, db)


@router.get("/embed/calendar", response_class=HTMLResponse, name="embed_calendar")
def embed_calendar(request: Request, db: Session = Depends(get_db)):
    import app as app_module

    return app_module.embed_calendar(request, db)


@router.api_route("/day/{date_str}", methods=["GET", "POST"], response_class=HTMLResponse, name="day_view")
async def day_view(request: Request, date_str: str, db: Session = Depends(get_db)):
    import app as app_module

    return await app_module.day_view(request, date_str, db)


@router.get("/routines", response_class=HTMLResponse, name="routines_list")
def routines_list(request: Request, db: Session = Depends(get_db)):
    import app as app_module

    return app_module.routines_list(request, db)


@router.get("/evaluation", response_class=HTMLResponse, name="evaluation_page")
def evaluation_page(request: Request):
    import app as app_module

    return app_module.evaluation_page(request)
