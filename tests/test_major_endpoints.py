import importlib
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


class _ExecResult:
    def __init__(self, items=None):
        self._items = list(items or [])

    def all(self):
        return list(self._items)

    def first(self):
        return self._items[0] if self._items else None


class _FakeDb:
    def __init__(self, queued_results=None, default_items=None):
        self.queued_results = list(queued_results or [])
        self.default_items = list(default_items or [])
        self.exec_calls = []
        self.added = []
        self.deleted = []
        self.commit_count = 0
        self.rollback_count = 0

    def exec(self, statement):
        self.exec_calls.append(statement)
        if self.queued_results:
            return _ExecResult(self.queued_results.pop(0))
        return _ExecResult(self.default_items)

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)

    def get(self, _model, _identifier):
        return None

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1

    def flush(self):
        return None

    def close(self):
        return None


@pytest.fixture()
def app_module(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "test-secret")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg2://scheduler:scheduler@localhost:5432/scheduler_test",
    )

    if "app" in sys.modules:
        del sys.modules["app"]
    loaded_app = importlib.import_module("app")
    monkeypatch.setattr(loaded_app, "_ensure_db_initialized", lambda: None)
    return loaded_app


@contextmanager
def _client_with_db(app_module, fake_db):
    app_module.app.dependency_overrides[app_module.get_db] = lambda: fake_db
    with TestClient(app_module.app) as client:
        yield client
    app_module.app.dependency_overrides.clear()


def test_calendar_endpoint_rollover_and_payload_shape(app_module, monkeypatch):
    fake_db = _FakeDb(default_items=[])
    monkeypatch.setattr(app_module, "get_weekday_routines", lambda _db, _weekday: [])

    with _client_with_db(app_module, fake_db) as client:
        response = client.get("/api/calendar?year=2026&month=13")

    assert response.status_code == 200
    payload = response.json()
    assert payload["year"] == 2027
    assert payload["month"] == 1
    assert payload["calendar_data"]
    assert all(len(week) == 7 for week in payload["calendar_data"])
    day = payload["calendar_data"][0][0]
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
    }.issubset(day.keys())


def test_day_endpoint_rejects_invalid_date(app_module):
    with _client_with_db(app_module, _FakeDb()) as client:
        response = client.get("/api/day/not-a-date")

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid date format"


def test_day_endpoint_serializes_timeline_items(app_module, monkeypatch):
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
    monkeypatch.setattr(app_module, "_get_timeline_data", lambda _db, _date: (timeline_items, 67))
    fake_db = _FakeDb(queued_results=[[SimpleNamespace(content="daily note")]])

    with _client_with_db(app_module, fake_db) as client:
        response = client.get("/api/day/2026-02-10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["date"] == "2026-02-10"
    assert payload["completion_rate"] == 67
    assert payload["day_log_content"] == "daily note"
    assert len(payload["timeline_items"]) == 2
    assert payload["timeline_items"][0]["step_name"] == "Stretch"
    assert payload["timeline_items"][0]["is_done"] is True
    assert payload["timeline_items"][1]["step_name"] == "Meeting"
    assert payload["timeline_items"][1]["is_done"] is True


def test_routines_by_day_endpoint_sorts_steps_by_time(app_module, monkeypatch):
    routine = SimpleNamespace(
        id=1,
        name="Morning Routine",
        description="desc",
        steps=[
            SimpleNamespace(id=11, name="Emails", time="11:00", category="Work"),
            SimpleNamespace(id=12, name="Coffee", time="08:00", category="Lifestyle"),
        ],
    )
    monkeypatch.setattr(app_module, "get_weekday_routines", lambda _db, _weekday: [routine])

    with _client_with_db(app_module, _FakeDb()) as client:
        response = client.get("/api/routines/day/2")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["routines"]) == 1
    assert [step["time"] for step in payload["routines"][0]["steps"]] == ["08:00", "11:00"]


def test_chat_endpoint_rejects_non_list_messages(app_module):
    with _client_with_db(app_module, _FakeDb()) as client:
        response = client.post("/api/chat", json={"messages": "invalid"})

    assert response.status_code == 400
    assert response.json()["detail"] == "messages must be a list"


def test_chat_endpoint_rejects_last_non_user_message(app_module):
    payload = {"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}]}

    with _client_with_db(app_module, _FakeDb()) as client:
        response = client.post("/api/chat", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "last message must be from user"


def test_chat_endpoint_passes_only_recent_ten_messages(app_module, monkeypatch):
    captured = {}

    def _fake_process_chat_request(_db, recent_messages):
        captured["recent_messages"] = recent_messages
        return {
            "reply": "ok",
            "should_refresh": False,
            "modified_ids": [],
            "execution_trace": [],
        }

    monkeypatch.setattr(app_module, "process_chat_request", _fake_process_chat_request)

    messages = [{"role": "user", "content": f"m{i}"} for i in range(11)]

    with _client_with_db(app_module, _FakeDb()) as client:
        response = client.post("/api/chat", json={"messages": messages})

    assert response.status_code == 200
    assert response.json()["reply"] == "ok"
    assert len(captured["recent_messages"]) == 10
    assert captured["recent_messages"][0]["content"] == "m1"
    assert captured["recent_messages"][-1]["content"] == "m10"


def test_model_settings_rejects_invalid_selection_type(app_module):
    with _client_with_db(app_module, _FakeDb()) as client:
        response = client.post("/model_settings", json={"selection": "bad"})

    assert response.status_code == 400
    assert response.json()["detail"] == "selection must be an object"


def test_model_settings_accepts_nested_scheduler_selection(app_module, monkeypatch):
    monkeypatch.setattr(
        app_module,
        "update_override",
        lambda _selection: ("openai", "gpt-4o-mini", "https://api.openai.com/v1", {}),
    )

    with _client_with_db(app_module, _FakeDb()) as client:
        response = client.post(
            "/model_settings",
            json={"selection": {"scheduler": {"provider": "openai", "model": "gpt-4o-mini"}}},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["applied"]["provider"] == "openai"
    assert payload["applied"]["model"] == "gpt-4o-mini"
