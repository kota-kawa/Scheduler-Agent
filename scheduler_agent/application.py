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
    # 日本語: 逆プロキシ配下運用を想定して root_path を環境変数から解決 / English: Resolve root_path from env for reverse-proxy deployments
    proxy_prefix = os.getenv("PROXY_PREFIX", PROXY_PREFIX)
    # 日本語: 実行時の SESSION_SECRET を優先 / English: Prefer runtime SESSION_SECRET override
    session_secret = os.getenv("SESSION_SECRET") or SESSION_SECRET

    # 日本語: FastAPI アプリ本体を作成 / English: Create root FastAPI application
    app = FastAPI(root_path=proxy_prefix)
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

    if not session_secret:
        raise ValueError("SESSION_SECRET environment variable is not set. Please set it in secrets.env.")

    # 日本語: セッション管理と静的配信を初期化 / English: Configure session middleware and static assets
    app.add_middleware(SessionMiddleware, secret_key=session_secret)
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    # 日本語: 機能別ルーターを順次登録 / English: Register feature routers
    app.include_router(calendar_router)
    app.include_router(chat_router)
    app.include_router(day_router)
    app.include_router(evaluation_router)
    app.include_router(model_router)
    app.include_router(page_router)
    app.include_router(routines_router)

    @app.on_event("startup")
    def _startup_init_db() -> None:
        # 日本語: 起動時にマイグレーション適用を保証 / English: Ensure migrations are applied on startup
        _init_db()

    return app


# 日本語: import 時点で既定アプリを構築 / English: Build default app instance at import time
app = create_app()
