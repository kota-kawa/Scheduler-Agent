"""Scheduler domain SQLModel models."""

import datetime

from sqlalchemy import Column, Text
from sqlmodel import Field, Relationship, SQLModel


# 日本語: 週次で繰り返す習慣の親エンティティ / English: Parent entity for recurring weekly routines
class Routine(SQLModel, table=True):
    __tablename__ = "routine"

    # 日本語: カンマ区切り曜日(0=月 ... 6=日) / English: Comma-separated weekdays (0=Mon ... 6=Sun)
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    days: str = Field(default="0,1,2,3,4", max_length=50)
    description: str | None = Field(default=None, max_length=200)
    steps: list["Step"] = Relationship(
        back_populates="routine", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


# 日本語: ルーチンを構成する個別ステップ / English: Atomic step inside a routine
class Step(SQLModel, table=True):
    __tablename__ = "step"

    id: int | None = Field(default=None, primary_key=True)
    routine_id: int = Field(foreign_key="routine.id")
    name: str = Field(max_length=100)
    time: str = Field(default="00:00", max_length=10)
    category: str = Field(default="Other", max_length=50)
    memo: str | None = Field(default=None, max_length=200)

    routine: Routine | None = Relationship(back_populates="steps")


# 日本語: 日付単位で保持するステップ実行ログ / English: Per-day completion log for routine steps
class DailyLog(SQLModel, table=True):
    __tablename__ = "daily_log"

    id: int | None = Field(default=None, primary_key=True)
    date: datetime.date
    step_id: int = Field(foreign_key="step.id")
    done: bool = Field(default=False)
    memo: str | None = Field(default=None, max_length=200)

    step: Step | None = Relationship()


# 日本語: 任意日に追加する単発タスク / English: One-off custom task bound to a specific date
class CustomTask(SQLModel, table=True):
    __tablename__ = "custom_task"

    id: int | None = Field(default=None, primary_key=True)
    date: datetime.date
    name: str = Field(max_length=100)
    time: str = Field(default="00:00", max_length=10)
    done: bool = Field(default=False)
    memo: str | None = Field(default=None, max_length=200)


# 日本語: 1日全体の自由記述メモ / English: Free-form day-level journal entry
class DayLog(SQLModel, table=True):
    __tablename__ = "day_log"

    id: int | None = Field(default=None, primary_key=True)
    date: datetime.date
    content: str | None = Field(default=None, sa_column=Column(Text))
