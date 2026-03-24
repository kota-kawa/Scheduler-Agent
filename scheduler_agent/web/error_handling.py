"""Shared API error handling helpers."""

from __future__ import annotations

import logging

from fastapi import HTTPException

logger = logging.getLogger("scheduler_agent.error_handling")


def raise_internal_server_error(user_message: str, *, exc: Exception | None = None) -> None:
    if exc is not None:
        logger.exception(user_message, exc_info=exc)
    else:
        logger.error(user_message)
    raise HTTPException(status_code=500, detail=user_message)
