"""Alembic migration helpers."""

from __future__ import annotations

from scheduler_agent.core.config import BASE_DIR


def _build_alembic_config(database_url: str):
    try:
        from alembic.config import Config
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency error path
        raise RuntimeError("Alembic is required. Install dependencies and retry.") from exc

    config = Config(str(BASE_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BASE_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def upgrade_to_head(database_url: str) -> None:
    """Apply migrations to the latest revision."""
    try:
        from alembic import command
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency error path
        raise RuntimeError("Alembic is required. Install dependencies and retry.") from exc

    command.upgrade(_build_alembic_config(database_url), "head")
