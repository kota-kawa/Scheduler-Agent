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


def get_monthly_llm_request_limit() -> int:
    """Maximum outbound LLM API requests allowed per calendar month."""
    # 日本語: 月次LLMリクエスト上限（未設定時は1000） / English: Monthly LLM request cap (default 1000 when unset)
    raw_value = os.getenv("SCHEDULER_MONTHLY_LLM_REQUEST_LIMIT", "1000")
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        parsed = 1000
    return max(1, parsed)


def get_max_input_chars() -> int:
    """Maximum accepted user input length in characters."""
    # 日本語: ユーザー入力文字数上限（未設定時は10000） / English: User input character cap (default 10000 when unset)
    raw_value = os.getenv("SCHEDULER_MAX_INPUT_CHARS", "10000")
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        parsed = 10000
    return max(1, parsed)


def get_max_output_tokens() -> int:
    """Maximum output tokens per LLM completion call."""
    # 日本語: 1リクエストあたりの出力トークン上限（未設定時は5000） / English: Per-request output token cap (default 5000 when unset)
    raw_value = os.getenv("SCHEDULER_MAX_OUTPUT_TOKENS", "5000")
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        parsed = 5000
    return max(1, parsed)
