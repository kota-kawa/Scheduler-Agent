import asyncio
import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from scheduler_agent.web import handlers as web_handlers


class _ExecResult:
    def __init__(self, items=None):
        self._items = list(items or [])

    def all(self):
        return list(self._items)

    def first(self):
        return self._items[0] if self._items else None


class _FakeDb:
    def __init__(self, queued_results=None):
        self.queued_results = list(queued_results or [])
        self.exec_calls = []
        self.commit_count = 0
        self.rollback_count = 0

    def exec(self, statement):
        self.exec_calls.append(statement)
        if self.queued_results:
            return _ExecResult(self.queued_results.pop(0))
        return _ExecResult([])

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


class _FakeRequest:
    def __init__(self, payload=None, method="POST", query_params=None):
        self._payload = payload if payload is not None else {}
        self.method = method
        self.query_params = query_params or {}
        self.headers = {}
        self.cookies = {}
        self.state = SimpleNamespace(guest_context=SimpleNamespace(guest_id="test-guest-id"))

    async def json(self):
        return self._payload


def test_api_calendar_rollover_and_payload_shape():
    payload = web_handlers.api_calendar(
        _FakeRequest(query_params={"year": "2026", "month": "13"}),
        _FakeDb(),
        get_weekday_routines_fn=lambda _db, _weekday: [],
    )

    assert payload["year"] == 2027
    assert payload["month"] == 1
    assert payload["calendar_data"]
    first_day = payload["calendar_data"][0][0]
    assert {
        "date",
        "day_num",
        "is_current_month",
        "routine_count",
        "custom_task_count",
        "total_routines",
        "total_steps",
        "completed_steps",
        "has_day_log",
    }.issubset(first_day.keys())


def test_api_day_view_serializes_timeline_items():
    timeline_items = [
        {
            "type": "routine",
            "time": "07:30",
            "id": "item_step_1",
            "routine": {"name": "Morning"},
            "step": {"name": "Stretch", "category": "Lifestyle"},
            "log": {"done": True, "memo": "done"},
            "real_obj": None,
        },
        {
            "type": "custom",
            "time": "10:00",
            "id": "item_custom_2",
            "routine": SimpleNamespace(name="Work"),
            "step": SimpleNamespace(name="Meeting", category="Business"),
            "log": SimpleNamespace(done=False, memo="pending"),
            "real_obj": SimpleNamespace(done=True),
        },
    ]
    db = _FakeDb(queued_results=[[SimpleNamespace(content="daily note")]])

    payload = web_handlers.api_day_view(
        "2026-02-10",
        db,
        get_timeline_data_fn=lambda _db, _date: (timeline_items, 67),
    )

    assert payload["date"] == "2026-02-10"
    assert payload["completion_rate"] == 67
    assert payload["day_log_content"] == "daily note"
    assert len(payload["timeline_items"]) == 2
    assert payload["timeline_items"][0]["step_name"] == "Stretch"
    assert payload["timeline_items"][0]["is_done"] is True
    assert payload["timeline_items"][1]["step_name"] == "Meeting"
    assert payload["timeline_items"][1]["is_done"] is True


def test_api_routines_by_day_sorts_steps():
    routine = SimpleNamespace(
        id=1,
        name="Morning Routine",
        description="desc",
        steps=[
            SimpleNamespace(id=11, name="Emails", time="11:00", category="Work"),
            SimpleNamespace(id=12, name="Coffee", time="08:00", category="Lifestyle"),
        ],
    )

    payload = web_handlers.api_routines_by_day(
        2,
        _FakeDb(),
        get_weekday_routines_fn=lambda _db, _weekday: [routine],
    )

    assert len(payload["routines"]) == 1
    assert [step["time"] for step in payload["routines"][0]["steps"]] == ["08:00", "11:00"]


def test_chat_rejects_non_list_messages():
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            web_handlers.chat(
                _FakeRequest(payload={"messages": "invalid"}),
                _FakeDb(),
                process_chat_request_fn=lambda *_args, **_kwargs: {},
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "messages must be a list"


def test_chat_rejects_last_non_user_message():
    payload = {"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}]}

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            web_handlers.chat(
                _FakeRequest(payload=payload),
                _FakeDb(),
                process_chat_request_fn=lambda *_args, **_kwargs: {},
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "last message must be from user"


def test_chat_rejects_when_last_user_message_exceeds_input_limit(monkeypatch):
    monkeypatch.setattr(web_handlers, "get_max_input_chars", lambda: 5)
    payload = {"messages": [{"role": "user", "content": "123456"}]}

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            web_handlers.chat(
                _FakeRequest(payload=payload),
                _FakeDb(),
                process_chat_request_fn=lambda *_args, **_kwargs: {},
            )
        )

    assert exc_info.value.status_code == 400
    assert "input exceeds max length" in exc_info.value.detail


def test_chat_passes_only_recent_ten_messages():
    captured = {}

    def _fake_process_chat_request(_db, recent_messages, guest_id="default"):
        captured["recent_messages"] = recent_messages
        captured["guest_id"] = guest_id
        return {"reply": "ok", "should_refresh": False, "modified_ids": [], "execution_trace": []}

    payload = {"messages": [{"role": "user", "content": f"m{i}"} for i in range(11)]}
    result = asyncio.run(
        web_handlers.chat(
            _FakeRequest(payload=payload),
            _FakeDb(),
            process_chat_request_fn=_fake_process_chat_request,
        )
    )

    assert result["reply"] == "ok"
    assert len(captured["recent_messages"]) == 10
    assert captured["recent_messages"][0]["content"] == "m1"
    assert captured["recent_messages"][-1]["content"] == "m10"
    assert captured["guest_id"] == "test-guest-id"


def test_evaluation_reset_deletes_scoped_evaluation_result():
    db = _FakeDb()

    result = web_handlers.evaluation_reset(
        _FakeRequest(),
        db,
        delete_fn=lambda _model: "DELETE",
    )

    assert result["status"] == "ok"
    assert db.commit_count == 1
    assert len(db.exec_calls) == 6


def test_update_model_settings_accepts_nested_scheduler_selection():
    result = asyncio.run(
        web_handlers.update_model_settings(
            _FakeRequest(
                payload={"selection": {"scheduler": {"provider": "openai", "model": "gpt-4o-mini"}}}
            ),
            update_override_fn=lambda _selection: (
                "openai",
                "gpt-4o-mini",
                "https://api.openai.com/v1",
                "",
            ),
        )
    )

    assert result["status"] == "ok"
    assert result["applied"]["provider"] == "openai"
    assert result["applied"]["model"] == "gpt-4o-mini"


def test_manage_chat_history_get_extracts_execution_trace():
    db = _FakeDb(
        queued_results=[
            [
                SimpleNamespace(
                    role="assistant",
                    content="stored text",
                    timestamp=datetime.datetime(2026, 2, 10, 8, 30, 0),
                )
            ]
        ]
    )

    result = asyncio.run(
        web_handlers.manage_chat_history(
            _FakeRequest(method="GET"),
            db,
            extract_execution_trace_fn=lambda _content: ("clean text", [{"round": 1}]),
            delete_fn=lambda _model: "DELETE",
        )
    )

    assert result["history"][0]["content"] == "clean text"
    assert result["history"][0]["execution_trace"] == [{"round": 1}]


def test_manage_chat_history_delete_commits():
    db = _FakeDb()

    result = asyncio.run(
        web_handlers.manage_chat_history(
            _FakeRequest(method="DELETE"),
            db,
            extract_execution_trace_fn=lambda _content: ("", []),
            delete_fn=lambda _model: "DELETE",
        )
    )

    assert result == {"status": "cleared"}
    assert db.commit_count == 1
    assert db.exec_calls == ["DELETE"]


def test_evaluation_seed_period_validates_date_order():
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            web_handlers.evaluation_seed_period(
                _FakeRequest(payload={"start_date": "2026-02-12", "end_date": "2026-02-11"}),
                _FakeDb(),
                seed_evaluation_data_fn=lambda *_args, **_kwargs: [],
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "start_date cannot be after end_date"


def test_evaluation_reset_rejects_when_dangerous_api_disabled(monkeypatch):
    monkeypatch.setattr(web_handlers, "dangerous_evaluation_api_enabled", lambda: False)

    with pytest.raises(HTTPException) as exc_info:
        web_handlers.evaluation_reset(_FakeRequest(), _FakeDb(), delete_fn=lambda _model: "DELETE")

    assert exc_info.value.status_code == 403
