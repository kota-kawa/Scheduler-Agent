"""Template helpers and flash storage."""

from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import urlencode, urlparse

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from scheduler_agent.core.config import BASE_DIR

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def flash(request: Request, message: str) -> None:
    flashes = request.session.setdefault("_flashes", [])
    flashes.append(message)
    request.session["_flashes"] = flashes


def pop_flashed_messages(request: Request) -> List[str]:
    return request.session.pop("_flashes", [])


def template_response(request: Request, template_name: str, context: Dict[str, Any]) -> HTMLResponse:
    payload = dict(context)
    payload.setdefault("request", request)

    forwarded_prefix = (request.headers.get("x-forwarded-prefix") or "").strip()
    if "," in forwarded_prefix:
        forwarded_prefix = forwarded_prefix.split(",", 1)[0].strip()
    proxy_prefix = forwarded_prefix or request.scope.get("root_path", "")
    if proxy_prefix and not proxy_prefix.startswith("/"):
        proxy_prefix = f"/{proxy_prefix}"
    proxy_prefix = proxy_prefix.rstrip("/") if proxy_prefix not in {"", "/"} else ""

    payload.setdefault("proxy_prefix", proxy_prefix)

    def _apply_proxy_prefix(path: str) -> str:
        if not proxy_prefix:
            return path
        if path.startswith(proxy_prefix):
            return path
        return f"{proxy_prefix}{path}"

    def _url_for(endpoint: str, **values: Any) -> str:
        param_names: set[str] = set()
        for route in request.app.router.routes:
            if getattr(route, "name", None) == endpoint:
                param_names = set(getattr(route, "param_convertors", {}).keys())
                break
        if values and not param_names:
            try:
                raw_url = str(request.url_for(endpoint, **values))
                parsed = urlparse(raw_url)
                path = parsed.path or "/"
                query = parsed.query
                path = _apply_proxy_prefix(path)
                return f"{path}?{query}" if query else path
            except Exception:
                pass
        path_params = {k: v for k, v in values.items() if k in param_names}
        query_params = {k: v for k, v in values.items() if k not in param_names}
        raw_url = str(request.url_for(endpoint, **path_params))
        parsed = urlparse(raw_url)
        path = parsed.path or "/"
        path = _apply_proxy_prefix(path)
        if query_params:
            return f"{path}?{urlencode(query_params)}"
        return path

    payload.setdefault("url_for", _url_for)
    payload.setdefault("get_flashed_messages", lambda: pop_flashed_messages(request))
    return templates.TemplateResponse(template_name, payload)
