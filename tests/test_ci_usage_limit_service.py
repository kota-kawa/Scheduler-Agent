import datetime

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from scheduler_agent.models import LlmMonthlyUsage
from scheduler_agent.services import usage_limit_service as usage_service


def _session_factory(engine):
    def _factory():
        return Session(engine)

    return _factory


@pytest.fixture()
def usage_engine():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine, tables=[LlmMonthlyUsage.__table__])
    return engine


def test_reserve_monthly_llm_request_increments_usage(usage_engine, monkeypatch):
    monkeypatch.setenv("SCHEDULER_MONTHLY_LLM_REQUEST_LIMIT", "2")
    now = datetime.datetime(2026, 3, 24, 10, 0, 0)
    session_factory = _session_factory(usage_engine)

    first = usage_service.reserve_monthly_llm_request(now=now, session_factory=session_factory)
    second = usage_service.reserve_monthly_llm_request(now=now, session_factory=session_factory)
    third = usage_service.reserve_monthly_llm_request(now=now, session_factory=session_factory)

    assert first.allowed is True
    assert first.used_before == 0
    assert first.used_after == 1
    assert first.remaining_after == 1

    assert second.allowed is True
    assert second.used_before == 1
    assert second.used_after == 2
    assert second.remaining_after == 0

    assert third.allowed is False
    assert third.used_before == 2
    assert third.used_after == 2
    assert third.remaining_after == 0


def test_reserve_monthly_llm_request_or_raise_raises_when_exhausted(usage_engine, monkeypatch):
    monkeypatch.setenv("SCHEDULER_MONTHLY_LLM_REQUEST_LIMIT", "1")
    now = datetime.datetime(2026, 4, 1, 9, 0, 0)
    session_factory = _session_factory(usage_engine)

    usage_service.reserve_monthly_llm_request_or_raise(now=now, session_factory=session_factory)

    with pytest.raises(usage_service.MonthlyLlmRequestLimitExceeded) as exc_info:
        usage_service.reserve_monthly_llm_request_or_raise(now=now, session_factory=session_factory)

    message = str(exc_info.value)
    assert "上限" in message
    assert "1000" not in message


def test_monthly_limit_message_points_to_next_month():
    message = usage_service.monthly_limit_reached_message(1000, year=2026, month=12)
    assert "1000" in message
    assert "2027年1月" in message


def test_usage_snapshot_returns_defaults_when_no_rows(usage_engine, monkeypatch):
    monkeypatch.delenv("SCHEDULER_MONTHLY_LLM_REQUEST_LIMIT", raising=False)
    now = datetime.datetime(2026, 6, 10, 8, 30, 0)
    snapshot = usage_service.get_monthly_llm_usage_snapshot(
        now=now,
        session_factory=_session_factory(usage_engine),
    )

    assert snapshot["year"] == 2026
    assert snapshot["month"] == 6
    assert snapshot["limit"] == 1000
    assert snapshot["used"] == 0
    assert snapshot["remaining"] == 1000

