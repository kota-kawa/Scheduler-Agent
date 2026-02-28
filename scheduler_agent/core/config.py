"""Core configuration for Scheduler Agent."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 日本語: ルート直下の secrets.env を起動時に読み込む / English: Load root-level secrets.env on startup
load_dotenv("secrets.env")

# 日本語: プロジェクトルート基準パス / English: Project root directory
BASE_DIR = Path(__file__).resolve().parents[2]

# 日本語: PostgreSQL 接続先の既定値 / English: Default PostgreSQL connection URL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://scheduler:scheduler@localhost:5432/scheduler",
)

# 日本語: 逆プロキシ配下向けプレフィックス / English: Prefix for reverse-proxy deployments
PROXY_PREFIX = os.getenv("PROXY_PREFIX", "")
# 日本語: セッション署名キー / English: Session signing secret
SESSION_SECRET = os.getenv("SESSION_SECRET")

# 日本語: assistant 応答に execution trace を埋め込むためのマーカー / English: Markers for embedding execution trace in stored replies
EXEC_TRACE_MARKER_PREFIX = "[[EXEC_TRACE_B64:"
EXEC_TRACE_MARKER_SUFFIX = "]]"


def get_max_action_rounds() -> int:
    """Maximum rounds for multi-step scheduler execution."""
    # 日本語: 過大値や不正値を防ぐため 1〜10 にクランプ / English: Clamp to 1-10 to avoid unsafe values
    raw_value = os.getenv("SCHEDULER_MAX_ACTION_ROUNDS", "10")
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        parsed = 10
    return max(1, min(parsed, 10))


def get_max_same_read_action_streak() -> int:
    """Maximum repeated identical read-only action streak."""
    # 日本語: 読み取りアクションの無限ループを防止 / English: Prevent infinite loops of repeated read actions
    raw_value = os.getenv("SCHEDULER_MAX_SAME_READ_ACTION_STREAK", "10")
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        parsed = 10
    return max(1, min(parsed, 10))
