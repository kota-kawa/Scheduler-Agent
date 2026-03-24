"""FastAPI application assembly."""

from __future__ import annotations

import asyncio
import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

try:
    from starlette.middleware.proxy_headers import ProxyHeadersMiddleware
except ModuleNotFoundError:  # pragma: no cover
    class ProxyHeadersMiddleware:  # type: ignore[no-redef]
        def __init__(self, app, trusted_hosts="*"):
            self.app = app

        async def __call__(self, scope, receive, send):
            await self.app(scope, receive, send)

from scheduler_agent.core.config import (
    BASE_DIR,
    PROXY_PREFIX,
    SESSION_SECRET,
    guest_cookie_max_age_seconds,
    guest_cookie_name,
    https_redirect_enabled,
    proxy_trusted_hosts,
    request_timeout_seconds,
    session_cookie_https_only,
    session_cookie_max_age_seconds,
    session_cookie_name,
    session_cookie_same_site,
    trusted_host_patterns,
)
from scheduler_agent.core.db import _init_db, create_session
from scheduler_agent.services.guest_data_service import cleanup_expired_guest_data_if_due
from scheduler_agent.web.routers import (
    calendar_router,
    chat_router,
    day_router,
    evaluation_router,
    model_router,
    page_router,
    routines_router,
)
from scheduler_agent.web.security import (
    enforce_request_body_limit,
    enforce_request_rate_limit,
    resolve_guest_context,
)

logger = logging.getLogger("scheduler_agent.application")


def create_app() -> FastAPI:
    # 日本語: 逆プロキシ配下運用を想定して root_path を環境変数から解決 / English: Resolve root_path from env for reverse-proxy deployments
    proxy_prefix = os.getenv("PROXY_PREFIX", PROXY_PREFIX)
    # 日本語: 実行時の SESSION_SECRET を優先 / English: Prefer runtime SESSION_SECRET override
    session_secret = os.getenv("SESSION_SECRET") or SESSION_SECRET

    # 日本語: FastAPI アプリ本体を作成 / English: Create root FastAPI application
    app = FastAPI(root_path=proxy_prefix)

    if not session_secret:
        raise ValueError("SESSION_SECRET environment variable is not set. Please set it in secrets.env.")

    # 日本語: セッション管理と静的配信を初期化 / English: Configure session middleware and static assets
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret,
        session_cookie=session_cookie_name(),
        max_age=session_cookie_max_age_seconds(),
        same_site=session_cookie_same_site(),
        https_only=session_cookie_https_only(),
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_host_patterns())
    if https_redirect_enabled():
        app.add_middleware(HTTPSRedirectMiddleware)
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=proxy_trusted_hosts())
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    @app.middleware("http")
    async def _security_guard_middleware(request: Request, call_next):
        if request.url.path.startswith("/static/"):
            return await call_next(request)

        enforce_request_rate_limit(request)
        await enforce_request_body_limit(request)

        guest_context = resolve_guest_context(request)
        request.state.guest_context = guest_context

        try:
            with create_session() as cleanup_db:
                cleanup_expired_guest_data_if_due(cleanup_db)
        except Exception:
            logger.exception("Guest cleanup failed.")

        timeout_seconds = request_timeout_seconds()
        try:
            response = await asyncio.wait_for(call_next(request), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return JSONResponse(
                status_code=504,
                content={
                    "detail": "Request timed out. Please retry with a smaller request.",
                },
            )

        if guest_context.is_anonymous:
            response.set_cookie(
                key=guest_cookie_name(),
                value=guest_context.guest_id,
                max_age=guest_cookie_max_age_seconds(),
                httponly=True,
                secure=session_cookie_https_only(),
                samesite=session_cookie_same_site(),
                path="/",
            )
        return response

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
