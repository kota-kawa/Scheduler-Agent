"""Core configuration for Scheduler Agent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import List

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


def _bool_env(name: str, default: bool) -> bool:
    # 日本語: 真偽値環境変数の安全な解釈 / English: Safely parse boolean environment variable
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int, minimum: int = 1, maximum: int | None = None) -> int:
    # 日本語: 整数環境変数の安全な解釈とクランプ / English: Parse integer env safely and clamp
    raw_value = os.getenv(name, str(default))
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        parsed = default
    if maximum is None:
        return max(minimum, parsed)
    return max(minimum, min(parsed, maximum))


def _csv_env(name: str, default: str) -> List[str]:
    # 日本語: CSV 環境変数を空要素除去して配列化 / English: Parse CSV env var into non-empty items
    raw = os.getenv(name, default)
    values = [item.strip() for item in str(raw).split(",")]
    return [item for item in values if item]


def is_production_environment() -> bool:
    # 日本語: 本番判定フラグ / English: Production-mode flag
    env = os.getenv("APP_ENV", os.getenv("ENV", "development"))
    return str(env).strip().lower() in {"production", "prod"}


def dangerous_evaluation_api_enabled() -> bool:
    # 日本語: 破壊的評価APIの公開可否 / English: Toggle for destructive evaluation endpoints
    return _bool_env(
        "SCHEDULER_ENABLE_DANGEROUS_EVAL_APIS",
        default=not is_production_environment(),
    )


def mcp_enabled() -> bool:
    # 日本語: MCP エンドポイント公開可否 / English: Toggle for exposing MCP endpoint
    return _bool_env("SCHEDULER_ENABLE_MCP", default=False)


def mcp_auth_token() -> str:
    # 日本語: MCP 固定トークン / English: Fixed token required for MCP access
    return str(os.getenv("SCHEDULER_MCP_AUTH_TOKEN", "")).strip()


def trusted_host_patterns() -> List[str]:
    # 日本語: Host ヘッダ許可リスト / English: Allowed Host header patterns
    return _csv_env(
        "SCHEDULER_TRUSTED_HOSTS",
        "localhost,127.0.0.1,testserver",
    )


def proxy_trusted_hosts() -> List[str]:
    # 日本語: ProxyHeaders を信頼する送信元ホスト / English: Trusted proxy hosts for ProxyHeaders middleware
    return _csv_env(
        "SCHEDULER_PROXY_TRUSTED_HOSTS",
        "127.0.0.1,::1,localhost",
    )


def https_redirect_enabled() -> bool:
    # 日本語: HTTPS リダイレクトの有効化 / English: Enable HTTPS redirect middleware
    return _bool_env(
        "SCHEDULER_FORCE_HTTPS",
        default=is_production_environment(),
    )


def session_cookie_https_only() -> bool:
    # 日本語: セッションCookieにSecure属性を付与 / English: Set Secure attribute on session cookie
    return _bool_env(
        "SCHEDULER_SESSION_HTTPS_ONLY",
        default=is_production_environment(),
    )


def session_cookie_same_site() -> str:
    # 日本語: SameSite 属性 / English: Session cookie SameSite attribute
    raw_value = str(os.getenv("SCHEDULER_SESSION_SAME_SITE", "lax")).strip().lower()
    if raw_value not in {"lax", "strict", "none"}:
        return "lax"
    return raw_value


def session_cookie_name() -> str:
    # 日本語: セッションCookie名 / English: Session cookie name
    raw_value = str(os.getenv("SCHEDULER_SESSION_COOKIE_NAME", "session")).strip()
    return raw_value or "session"


def session_cookie_max_age_seconds() -> int:
    # 日本語: セッションCookie有効期限 / English: Session cookie max age (seconds)
    return _int_env("SCHEDULER_SESSION_MAX_AGE_SECONDS", 60 * 60 * 24 * 7, minimum=60)


def guest_cookie_name() -> str:
    # 日本語: 匿名ゲスト識別Cookie名 / English: Anonymous guest identifier cookie name
    raw_value = str(os.getenv("SCHEDULER_GUEST_COOKIE_NAME", "guest_id")).strip()
    return raw_value or "guest_id"


def guest_cookie_max_age_seconds() -> int:
    # 日本語: ゲストCookie有効期限 / English: Guest cookie max age (seconds)
    return _int_env("SCHEDULER_GUEST_COOKIE_MAX_AGE_SECONDS", 60 * 60 * 24 * 3, minimum=60)


def guest_data_ttl_hours() -> int:
    # 日本語: 匿名データ保持期間（時間） / English: Guest data retention period in hours
    return _int_env("SCHEDULER_GUEST_DATA_TTL_HOURS", 72, minimum=1)


def guest_data_cleanup_interval_seconds() -> int:
    # 日本語: TTL掃除の最小実行間隔 / English: Minimum interval for TTL cleanup runs
    return _int_env("SCHEDULER_GUEST_CLEANUP_INTERVAL_SECONDS", 300, minimum=10)


def request_rate_limit_window_seconds() -> int:
    # 日本語: レート制限の時間窓 / English: Rate-limit rolling window in seconds
    return _int_env("SCHEDULER_RATE_LIMIT_WINDOW_SECONDS", 60, minimum=1)


def request_rate_limit_max_requests() -> int:
    # 日本語: IPごとの最大リクエスト数 / English: Max requests per IP within the rate-limit window
    return _int_env("SCHEDULER_RATE_LIMIT_MAX_REQUESTS", 120, minimum=1)


def request_timeout_seconds() -> int:
    # 日本語: APIタイムアウト秒数 / English: API request timeout in seconds
    return _int_env("SCHEDULER_REQUEST_TIMEOUT_SECONDS", 30, minimum=1)


def max_request_body_bytes() -> int:
    # 日本語: APIリクエスト本文サイズ上限 / English: Maximum API request body size in bytes
    return _int_env("SCHEDULER_MAX_REQUEST_BODY_BYTES", 262_144, minimum=1_024)


def protected_api_prefixes() -> List[str]:
    # 日本語: レート制限・ボディ上限の対象パス / English: Path prefixes protected by request guards
    return _csv_env("SCHEDULER_PROTECTED_API_PREFIXES", "/api/,/model_settings")


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
