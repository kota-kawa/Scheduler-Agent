import datetime

from scheduler_agent.services.reply_service import (
    _attach_execution_trace_to_stored_content,
    _extract_execution_trace_from_stored_content,
    _remove_no_schedule_lines,
)
from scheduler_agent.services.schedule_parser_service import _resolve_schedule_expression


def test_execution_trace_round_trip():
    content = "処理完了"
    trace = [{"round": 1, "actions": [{"type": "create_custom_task"}], "results": ["ok"], "errors": []}]

    stored = _attach_execution_trace_to_stored_content(content, trace)
    restored_content, restored_trace = _extract_execution_trace_from_stored_content(stored)

    assert restored_content == content
    assert restored_trace == trace


def test_remove_no_schedule_lines_filters_only_target_lines():
    source = "予定は以下です\n予定なし\n09:00 朝食\n予定 無し\n10:00 会議"
    cleaned = _remove_no_schedule_lines(source)

    assert "予定なし" not in cleaned
    assert "予定 無し" not in cleaned
    assert "09:00 朝食" in cleaned
    assert "10:00 会議" in cleaned


def test_resolve_schedule_expression_handles_relative_day_with_time():
    resolved = _resolve_schedule_expression(
        expression="3日後 14:30",
        base_date=datetime.date(2026, 2, 12),
        base_time="09:00",
        default_time="00:00",
    )

    assert resolved["ok"] is True
    assert resolved["date"] == "2026-02-15"
    assert resolved["time"] == "14:30"
