"""Add llm_monthly_usage table.

Revision ID: 20260324_000002
Revises: 20260225_000001
Create Date: 2026-03-24
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260324_000002"
down_revision = "20260225_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_monthly_usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False, server_default=sa.text("'all'")),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("year", "month", "scope", name="uq_llm_monthly_usage_year_month_scope"),
    )


def downgrade() -> None:
    op.drop_table("llm_monthly_usage")
