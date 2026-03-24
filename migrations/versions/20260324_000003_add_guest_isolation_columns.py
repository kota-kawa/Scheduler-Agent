"""Add guest isolation and retention columns.

Revision ID: 20260324_000003
Revises: 20260324_000002
Create Date: 2026-03-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260324_000003"
down_revision = "20260324_000002"
branch_labels = None
depends_on = None


def _add_guest_and_created_columns(table_name: str, has_timestamp: bool = False) -> None:
    op.add_column(
        table_name,
        sa.Column("guest_id", sa.String(length=64), nullable=False, server_default=sa.text("'default'")),
    )
    op.create_index(f"ix_{table_name}_guest_id", table_name, ["guest_id"])

    if not has_timestamp:
        op.add_column(
            table_name,
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )


def upgrade() -> None:
    _add_guest_and_created_columns("routine")
    _add_guest_and_created_columns("step")
    _add_guest_and_created_columns("daily_log")
    _add_guest_and_created_columns("custom_task")
    _add_guest_and_created_columns("day_log")
    _add_guest_and_created_columns("chat_history")
    _add_guest_and_created_columns("evaluation_result")


def _drop_guest_and_created_columns(table_name: str, has_timestamp: bool = False) -> None:
    op.drop_index(f"ix_{table_name}_guest_id", table_name=table_name)
    op.drop_column(table_name, "guest_id")
    if not has_timestamp:
        op.drop_column(table_name, "created_at")


def downgrade() -> None:
    _drop_guest_and_created_columns("evaluation_result")
    _drop_guest_and_created_columns("chat_history")
    _drop_guest_and_created_columns("day_log")
    _drop_guest_and_created_columns("custom_task")
    _drop_guest_and_created_columns("daily_log")
    _drop_guest_and_created_columns("step")
    _drop_guest_and_created_columns("routine")
