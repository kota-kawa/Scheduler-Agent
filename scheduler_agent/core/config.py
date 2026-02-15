"""Core configuration for Scheduler Agent."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load secrets from project root.
load_dotenv("secrets.env")

BASE_DIR = Path(__file__).resolve().parents[2]

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://scheduler:scheduler@localhost:5432/scheduler",
)

PROXY_PREFIX = os.getenv("PROXY_PREFIX", "")
SESSION_SECRET = os.getenv("SESSION_SECRET")

EXEC_TRACE_MARKER_PREFIX = "[[EXEC_TRACE_B64:"
EXEC_TRACE_MARKER_SUFFIX = "]]"


def get_max_action_rounds() -> int:
    """Maximum rounds for multi-step scheduler execution."""
    raw_value = os.getenv("SCHEDULER_MAX_ACTION_ROUNDS", "10")
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        parsed = 10
    return max(1, min(parsed, 10))


def get_max_same_read_action_streak() -> int:
    """Maximum repeated identical read-only action streak."""
    raw_value = os.getenv("SCHEDULER_MAX_SAME_READ_ACTION_STREAK", "10")
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        parsed = 10
    return max(1, min(parsed, 10))
