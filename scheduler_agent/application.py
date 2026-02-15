"""FastAPI application assembly."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

try:
    from starlette.middleware.proxy_headers import ProxyHeadersMiddleware
except ModuleNotFoundError:  # pragma: no cover
    class ProxyHeadersMiddleware:  # type: ignore[no-redef]
        def __init__(self, app, trusted_hosts="*"):
            self.app = app

        async def __call__(self, scope, receive, send):
            await self.app(scope, receive, send)

from scheduler_agent.core.config import BASE_DIR, PROXY_PREFIX, SESSION_SECRET
from scheduler_agent.core.db import _init_db
from scheduler_agent.web.routers import (
    calendar_router,
    chat_router,
    day_router,
    evaluation_router,
    model_router,
    page_router,
    routines_router,
)


def create_app() -> FastAPI:
    proxy_prefix = os.getenv("PROXY_PREFIX", PROXY_PREFIX)
    session_secret = os.getenv("SESSION_SECRET") or SESSION_SECRET

    app = FastAPI(root_path=proxy_prefix)
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

    if not session_secret:
        raise ValueError("SESSION_SECRET environment variable is not set. Please set it in secrets.env.")

    app.add_middleware(SessionMiddleware, secret_key=session_secret)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    app.include_router(calendar_router)
    app.include_router(chat_router)
    app.include_router(day_router)
    app.include_router(evaluation_router)
    app.include_router(model_router)
    app.include_router(page_router)
    app.include_router(routines_router)

    @app.on_event("startup")
    def _startup_init_db() -> None:
        _init_db()

    return app


app = create_app()
