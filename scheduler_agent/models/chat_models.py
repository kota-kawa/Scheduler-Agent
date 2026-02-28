"""Chat and evaluation SQLModel models."""

from __future__ import annotations

import datetime

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


# 日本語: ユーザー/アシスタント会話の永続化テーブル / English: Persistent chat transcript table
class ChatHistory(SQLModel, table=True):
    __tablename__ = "chat_history"

    id: int | None = Field(default=None, primary_key=True)
    role: str = Field(max_length=20)
    content: str = Field(sa_column=Column(Text, nullable=False))
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.now)


# 日本語: 評価実験の結果保存テーブル / English: Stored evaluation run results
class EvaluationResult(SQLModel, table=True):
    __tablename__ = "evaluation_result"

    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.now)
    model_name: str | None = Field(default=None, max_length=100)
    task_prompt: str | None = Field(default=None, sa_column=Column(Text))
    agent_reply: str | None = Field(default=None, sa_column=Column(Text))
    tool_calls: str | None = Field(default=None, sa_column=Column(Text))
    is_success: bool | None = Field(default=None)
    comments: str | None = Field(default=None, sa_column=Column(Text))
