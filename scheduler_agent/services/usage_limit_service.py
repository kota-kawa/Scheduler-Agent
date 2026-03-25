"""Monthly LLM API usage limiting service."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Dict

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from scheduler_agent.core.config import get_monthly_llm_request_limit
from scheduler_agent.core.db import create_session
from scheduler_agent.models import LlmMonthlyUsage

DEFAULT_SCOPE = "all"


@dataclass(frozen=True)
class MonthlyUsageReservation:
    allowed: bool
    year: int
    month: int
    scope: str
    limit: int
    used_before: int
    used_after: int
    remaining_after: int


class MonthlyLlmRequestLimitExceeded(RuntimeError):
    """Raised when monthly LLM request quota has been exhausted."""

    def __init__(self, reservation: MonthlyUsageReservation):
        self.reservation = reservation
        message = monthly_limit_reached_message(
            reservation.limit,
            year=reservation.year,
            month=reservation.month,
        )
        super().__init__(message)


def _current_year_month(now: datetime.datetime | None = None) -> tuple[int, int]:
    # 日本語: テスト時は now を優先し、未指定なら現在時刻を利用 / English: Prefer injected `now` for tests, otherwise use current time
    timestamp = now or datetime.datetime.now()
    return timestamp.year, timestamp.month


def _build_monthly_usage_select_statement(*, year: int, month: int, scope: str):
    # 日本語: 同一月・同一scopeの行をロック付きで取得するクエリを生成 / English: Build row-select query (with row lock when available) for month/scope
    statement = select(LlmMonthlyUsage).where(
        LlmMonthlyUsage.year == year,
        LlmMonthlyUsage.month == month,
        LlmMonthlyUsage.scope == scope,
    )
    if hasattr(statement, "with_for_update"):
        statement = statement.with_for_update()
    return statement


def reserve_monthly_llm_request(
    *,
    scope: str = DEFAULT_SCOPE,
    now: datetime.datetime | None = None,
    session_factory=create_session,
) -> MonthlyUsageReservation:
    """
    Reserve one outbound LLM API request from the current month's budget.

    Returns reservation details. When `allowed` is False, the request was not counted.
    """
    year, month = _current_year_month(now)
    normalized_scope = (scope or DEFAULT_SCOPE).strip() or DEFAULT_SCOPE
    monthly_limit = get_monthly_llm_request_limit()

    # 日本語: 競合挿入に備えて最大2回リトライ / English: Retry at most twice to handle concurrent insert race
    for attempt in range(2):
        with session_factory() as db:
            try:
                row = db.exec(
                    _build_monthly_usage_select_statement(
                        year=year,
                        month=month,
                        scope=normalized_scope,
                    )
                ).first()

                used_before = int(row.request_count) if row else 0
                if used_before >= monthly_limit:
                    # 日本語: 上限超過時はカウントを増やさず却下 / English: Reject without incrementing when quota is already exhausted
                    return MonthlyUsageReservation(
                        allowed=False,
                        year=year,
                        month=month,
                        scope=normalized_scope,
                        limit=monthly_limit,
                        used_before=used_before,
                        used_after=used_before,
                        remaining_after=0,
                    )

                if row is None:
                    # 日本語: 当月レコードが無ければ新規作成 / English: Create monthly row when it does not exist yet
                    row = LlmMonthlyUsage(
                        year=year,
                        month=month,
                        scope=normalized_scope,
                        request_count=1,
                        updated_at=now or datetime.datetime.now(),
                    )
                    db.add(row)
                    used_after = 1
                else:
                    # 日本語: 既存レコードの利用回数をインクリメント / English: Increment usage counter on existing monthly row
                    row.request_count = used_before + 1
                    row.updated_at = now or datetime.datetime.now()
                    db.add(row)
                    used_after = int(row.request_count)

                db.commit()
                remaining_after = max(monthly_limit - used_after, 0)
                return MonthlyUsageReservation(
                    allowed=True,
                    year=year,
                    month=month,
                    scope=normalized_scope,
                    limit=monthly_limit,
                    used_before=used_before,
                    used_after=used_after,
                    remaining_after=remaining_after,
                )
            except IntegrityError:
                db.rollback()
                if attempt == 1:
                    raise

    # Defensive fallback; loop either returns success/denied or raises.
    return MonthlyUsageReservation(
        allowed=False,
        year=year,
        month=month,
        scope=normalized_scope,
        limit=monthly_limit,
        used_before=monthly_limit,
        used_after=monthly_limit,
        remaining_after=0,
    )


def reserve_monthly_llm_request_or_raise(
    *,
    scope: str = DEFAULT_SCOPE,
    now: datetime.datetime | None = None,
    session_factory=create_session,
) -> MonthlyUsageReservation:
    """Reserve one monthly request and raise when the limit is exhausted."""
    # 日本語: 呼び出し側は例外ベースで上限制御できる / English: Provide exception-based flow control for callers
    reservation = reserve_monthly_llm_request(scope=scope, now=now, session_factory=session_factory)
    if not reservation.allowed:
        raise MonthlyLlmRequestLimitExceeded(reservation)
    return reservation


def _next_year_month(year: int, month: int) -> tuple[int, int]:
    if month >= 12:
        return year + 1, 1
    return year, month + 1


def monthly_limit_reached_message(limit: int, *, year: int, month: int) -> str:
    # 日本語: 上限超過時のユーザー向け定型文 / English: User-facing message when monthly limit has been reached
    next_year, next_month = _next_year_month(year, month)
    return (
        f"今月のLLM API利用上限（{limit}回）に達したため、新しいリクエストを実行できません。"
        f"{next_year}年{next_month}月の利用枠までお待ちください。"
    )


def get_monthly_llm_usage_snapshot(
    *,
    now: datetime.datetime | None = None,
    scope: str = DEFAULT_SCOPE,
    session_factory=create_session,
) -> Dict[str, int]:
    """Return current month usage/limit snapshot for observability and tests."""
    year, month = _current_year_month(now)
    normalized_scope = (scope or DEFAULT_SCOPE).strip() or DEFAULT_SCOPE
    monthly_limit = get_monthly_llm_request_limit()

    with session_factory() as db:
        row = db.exec(
            select(LlmMonthlyUsage).where(
                LlmMonthlyUsage.year == year,
                LlmMonthlyUsage.month == month,
                LlmMonthlyUsage.scope == normalized_scope,
            )
        ).first()
        used = int(row.request_count) if row else 0

    return {
        "year": year,
        "month": month,
        "limit": monthly_limit,
        "used": used,
        "remaining": max(monthly_limit - used, 0),
    }
