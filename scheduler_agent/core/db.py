"""Database engine and session helpers."""

from __future__ import annotations

import os
import threading
from typing import Iterator

from sqlmodel import Session, create_engine

from scheduler_agent.core.config import DATABASE_URL
from scheduler_agent.core.migrations import upgrade_to_head

DEFAULT_DATABASE_URL = "postgresql+psycopg2://scheduler:scheduler@localhost:5432/scheduler"


def _normalize_database_url(database_url: str) -> str:
    normalized_url = database_url or ""
    if normalized_url.startswith("postgres://"):
        normalized_url = normalized_url.replace("postgres://", "postgresql+psycopg2://", 1)
    if not normalized_url.startswith("postgresql"):
        raise ValueError("DATABASE_URL must be PostgreSQL (postgresql+psycopg2://...).")
    return normalized_url


def _build_engine(database_url: str):
    normalized_url = _normalize_database_url(database_url)
    return create_engine(normalized_url)


def _database_url_from_env() -> str:
    return os.getenv("DATABASE_URL", DATABASE_URL or DEFAULT_DATABASE_URL)


_current_database_url = _normalize_database_url(_database_url_from_env())
engine = _build_engine(_current_database_url)
_db_initialized = False
_db_init_lock = threading.Lock()


def refresh_engine_from_env() -> None:
    """Refresh engine if DATABASE_URL changed after initial module import."""
    global engine, _db_initialized, _current_database_url

    latest_database_url = _normalize_database_url(_database_url_from_env())
    if latest_database_url == _current_database_url:
        return

    engine = _build_engine(latest_database_url)
    _current_database_url = latest_database_url
    _db_initialized = False


def _ensure_db_initialized() -> None:
    global _db_initialized
    if _db_initialized:
        return
    with _db_init_lock:
        if _db_initialized:
            return
        upgrade_to_head(_current_database_url)
        _db_initialized = True


def _init_db() -> None:
    _ensure_db_initialized()


def create_session() -> Session:
    _ensure_db_initialized()
    return Session(engine)


def get_db() -> Iterator[Session]:
    _ensure_db_initialized()
    with Session(engine) as db:
        yield db
