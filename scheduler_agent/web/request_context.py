"""Request context helpers."""

from __future__ import annotations

import re

from fastapi import Request

from scheduler_agent.core.config import guest_cookie_name

_GUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _normalize_guest_id(value: str) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    if not _GUEST_ID_PATTERN.fullmatch(token):
        return ""
    return token


def get_guest_id_from_request(request: Request) -> str:
    state = getattr(request, "state", None)
    context = getattr(state, "guest_context", None) if state is not None else None
    guest_id = _normalize_guest_id(getattr(context, "guest_id", None))
    if guest_id:
        return guest_id
    headers = getattr(request, "headers", None)
    header_guest_id = _normalize_guest_id(headers.get("x-guest-id", "") if headers is not None else "")
    if header_guest_id:
        return header_guest_id
    cookies = getattr(request, "cookies", None)
    cookie_guest_id = _normalize_guest_id(
        cookies.get(guest_cookie_name(), "") if cookies is not None else ""
    )
    if cookie_guest_id:
        return cookie_guest_id
    return "default"
