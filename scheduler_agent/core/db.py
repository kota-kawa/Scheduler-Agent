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
    # 日本語: 旧 postgres:// を SQLAlchemy 推奨形式へ正規化 / English: Normalize legacy postgres:// URL to SQLAlchemy-friendly form
    normalized_url = database_url or ""
    if normalized_url.startswith("postgres://"):
        normalized_url = normalized_url.replace("postgres://", "postgresql+psycopg2://", 1)
    if not normalized_url.startswith("postgresql"):
        raise ValueError("DATABASE_URL must be PostgreSQL (postgresql+psycopg2://...).")
    return normalized_url


def _build_engine(database_url: str):
    # 日本語: URL検証後にエンジン生成 / English: Build engine after URL validation
    normalized_url = _normalize_database_url(database_url)
    return create_engine(normalized_url)


def _database_url_from_env() -> str:
    # 日本語: 実行時環境変数を優先 / English: Prefer runtime environment override
    return os.getenv("DATABASE_URL", DATABASE_URL or DEFAULT_DATABASE_URL)


# 日本語: モジュール初期化時点の接続情報とエンジン / English: Module-level current URL and engine
_current_database_url = _normalize_database_url(_database_url_from_env())
engine = _build_engine(_current_database_url)
_db_initialized = False
_db_init_lock = threading.Lock()


def refresh_engine_from_env() -> None:
    """Refresh engine if DATABASE_URL changed after initial module import."""
    global engine, _db_initialized, _current_database_url

    # 日本語: 環境差し替え時のみエンジンを再構築 / English: Rebuild engine only when URL actually changes
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
    # 日本語: マイグレーションはプロセス内で一度だけ実行 / English: Run migrations once per process with lock protection
    with _db_init_lock:
        if _db_initialized:
            return
        upgrade_to_head(_current_database_url)
        _db_initialized = True


def _init_db() -> None:
    # 日本語: 旧API互換の初期化エントリ / English: Backward-compatible initialization entrypoint
    _ensure_db_initialized()


def create_session() -> Session:
    # 日本語: 明示的セッション生成（MCP等で利用） / English: Explicit session factory (used by MCP, etc.)
    _ensure_db_initialized()
    return Session(engine)


def get_db() -> Iterator[Session]:
    # 日本語: FastAPI Depends 用のセッション供給器 / English: Dependency provider for FastAPI routes
    _ensure_db_initialized()
    with Session(engine) as db:
        yield db
