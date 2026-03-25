"""Chat and evaluation SQLModel models."""

from __future__ import annotations

import datetime

from sqlalchemy import Column, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


# 日本語: ユーザー/アシスタント会話の永続化テーブル / English: Persistent chat transcript table
class ChatHistory(SQLModel, table=True):
    __tablename__ = "chat_history"

    id: int | None = Field(default=None, primary_key=True)
    guest_id: str = Field(default="default", max_length=64, nullable=False, index=True)
    role: str = Field(max_length=20)
    content: str = Field(sa_column=Column(Text, nullable=False))
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.now)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.now, nullable=False)


# 日本語: 評価実験の結果保存テーブル / English: Stored evaluation run results
class EvaluationResult(SQLModel, table=True):
    __tablename__ = "evaluation_result"

    id: int | None = Field(default=None, primary_key=True)
    guest_id: str = Field(default="default", max_length=64, nullable=False, index=True)
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.now)
    model_name: str | None = Field(default=None, max_length=100)
    task_prompt: str | None = Field(default=None, sa_column=Column(Text))
    agent_reply: str | None = Field(default=None, sa_column=Column(Text))
    tool_calls: str | None = Field(default=None, sa_column=Column(Text))
    is_success: bool | None = Field(default=None)
    comments: str | None = Field(default=None, sa_column=Column(Text))
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.now, nullable=False)


# 日本語: 月次のLLM API利用回数カウンタ / English: Monthly LLM API usage counter
class LlmMonthlyUsage(SQLModel, table=True):
    __tablename__ = "llm_monthly_usage"
    # 日本語: 同月同scopeの重複行を禁止 / English: Prevent duplicate rows for the same year/month/scope
    __table_args__ = (
        UniqueConstraint("year", "month", "scope", name="uq_llm_monthly_usage_year_month_scope"),
    )

    id: int | None = Field(default=None, primary_key=True)
    year: int = Field(nullable=False)
    month: int = Field(nullable=False)
    scope: str = Field(default="all", max_length=32, nullable=False)
    request_count: int = Field(default=0, nullable=False)
    updated_at: datetime.datetime = Field(default_factory=datetime.datetime.now, nullable=False)
