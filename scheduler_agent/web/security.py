"""Security and request-guard helpers for public demo deployment."""

from __future__ import annotations

import ipaddress
import re
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable

from fastapi import HTTPException, Request

from scheduler_agent.core.config import (
    guest_cookie_max_age_seconds,
    guest_cookie_name,
    max_request_body_bytes,
    protected_api_prefixes,
    request_rate_limit_max_requests,
    request_rate_limit_window_seconds,
)

GUEST_ID_HEADER = "x-guest-id"
_PUBLIC_ENDPOINTS = {"/", "/favicon.ico"}
_REQUEST_COUNTERS: Dict[str, Deque[float]] = {}
_REQUEST_COUNTER_LOCK = threading.Lock()
_GUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


@dataclass(frozen=True)
class GuestContext:
    guest_id: str
    is_anonymous: bool


def _is_localhost(value: str) -> bool:
    token = str(value or "").strip().lower()
    if token in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(token).is_loopback
    except ValueError:
        return False


def _effective_client_ip(request: Request) -> str:
    # 日本語: localhost経由時のみ x-forwarded-for を信頼 / English: Trust x-forwarded-for only when direct client is localhost
    direct_client = request.client.host if request.client and request.client.host else ""
    direct_client = str(direct_client).strip()

    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for and _is_localhost(direct_client):
        forwarded_candidate = forwarded_for.split(",", 1)[0].strip()
        if forwarded_candidate:
            return forwarded_candidate
    return direct_client or "unknown"


def _normalize_guest_id(value: str) -> str:
    # 日本語: guest_id の形式を検証し不正値を除外 / English: Validate guest_id format and reject invalid tokens
    token = str(value or "").strip()
    if not token:
        return ""
    if not _GUEST_ID_PATTERN.fullmatch(token):
        return ""
    return token


def _is_protected_path(path: str, prefixes: Iterable[str] | None = None) -> bool:
    # 日本語: 公開パスを除き、保護対象prefix配下のみガードを適用 / English: Apply guards only to configured protected prefixes excluding public paths
    path_value = str(path or "")
    if path_value in _PUBLIC_ENDPOINTS:
        return False
    active_prefixes = list(prefixes or protected_api_prefixes())
    return any(path_value.startswith(prefix) for prefix in active_prefixes)


def enforce_request_rate_limit(request: Request) -> None:
    if not _is_protected_path(str(request.url.path)):
        return

    window_seconds = request_rate_limit_window_seconds()
    max_requests = request_rate_limit_max_requests()
    now = time.monotonic()
    client_ip = _effective_client_ip(request)
    key = f"{client_ip}:{request.url.path}"

    with _REQUEST_COUNTER_LOCK:
        # 日本語: スライディングウィンドウで古い記録を除去 / English: Evict stale timestamps for rolling-window rate limiting
        bucket = _REQUEST_COUNTERS.setdefault(key, deque())
        threshold = now - window_seconds
        while bucket and bucket[0] < threshold:
            bucket.popleft()
        if len(bucket) >= max_requests:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please slow down and try again.",
            )
        bucket.append(now)


async def enforce_request_body_limit(request: Request) -> None:
    # 日本語: Content-Length ヘッダで事前に本文サイズを検証 / English: Pre-check request body size using Content-Length header
    if not _is_protected_path(str(request.url.path)):
        return
    content_length = request.headers.get("content-length")
    if not content_length:
        return
    try:
        bytes_count = int(content_length)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid Content-Length header.")
    if bytes_count > max_request_body_bytes():
        raise HTTPException(status_code=413, detail="Request body is too large.")


def resolve_guest_context(request: Request) -> GuestContext:
    # 日本語: 既存IDがなければ匿名ゲストIDを新規発行 / English: Reuse provided guest ID or mint a new anonymous ID
    header_guest_id = _normalize_guest_id(request.headers.get(GUEST_ID_HEADER) or "")
    cookie_guest_id = _normalize_guest_id(request.cookies.get(guest_cookie_name()) or "")
    raw_guest_id = header_guest_id or cookie_guest_id
    if raw_guest_id:
        return GuestContext(guest_id=raw_guest_id, is_anonymous=False)

    generated_guest_id = _normalize_guest_id(secrets.token_urlsafe(18))
    if not generated_guest_id:
        generated_guest_id = secrets.token_hex(16)
    return GuestContext(guest_id=generated_guest_id, is_anonymous=True)
