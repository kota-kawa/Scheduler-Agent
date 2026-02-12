import asyncio
import datetime
from types import SimpleNamespace

import pytest

import app as app_module


class _ExecResult:
    def __init__(self, items=None):
        self._items = items or []

    def all(self):
        return list(self._items)

    def first(self):
        return self._items[0] if self._items else None


class _FakeSession:
    def __init__(self):
        self.added = []

    def exec(self, *args, **kwargs):
        return _ExecResult([])

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None

    def flush(self):
        return None


class _FakeRequest:
    def __init__(self, payload=None, method="POST"):
        self._payload = payload
        self.method = method

    async def json(self):
        return self._payload


@pytest.fixture()
def fake_db(monkeypatch):
    monkeypatch.setattr(app_module, "call_scheduler_llm", lambda *_args, **_kwargs: ("ok", []))
    monkeypatch.setattr(app_module, "_apply_actions", lambda *_args, **_kwargs: ([], [], []))
    monkeypatch.setattr(
        app_module,
        "process_chat_request",
        lambda *_args, **_kwargs: {"reply": "ok", "should_refresh": False, "modified_ids": []},
    )
    monkeypatch.setattr(app_module, "delete", lambda *_args, **_kwargs: object())
    return _FakeSession()


def test_chat_endpoint_basic(fake_db):
    request = _FakeRequest({"messages": [{"role": "user", "content": "hello"}]})
    res = asyncio.run(app_module.chat(request, db=fake_db))
    assert res["reply"] == "ok"


def test_chat_history_endpoints_basic(fake_db):
    res = asyncio.run(app_module.manage_chat_history(_FakeRequest(method="GET"), db=fake_db))
    assert res == {"history": []}

    res = asyncio.run(app_module.manage_chat_history(_FakeRequest(method="DELETE"), db=fake_db))
    assert res.get("status") == "cleared"


def test_conversation_review_endpoint_removed():
    assert not hasattr(app_module, "review_conversation_history")


def test_process_chat_request_supports_multi_step(monkeypatch):
    db = _FakeSession()
    llm_calls = []
    apply_calls = []

    llm_sequence = [
        ("まず予定を確認します。", [{"type": "get_daily_summary", "date": "2026-02-12"}]),
        (
            "予定を追加します。",
            [{"type": "create_custom_task", "name": "歯医者", "date": "2026-02-12", "time": "10:00"}],
        ),
        ("確認完了です。", []),
    ]

    def _fake_call_scheduler_llm(messages, context):
        llm_calls.append({"messages": list(messages), "context": context})
        return llm_sequence[len(llm_calls) - 1]

    def _fake_apply_actions(_db, actions, _today):
        apply_calls.append(list(actions))
        action_type = actions[0].get("type")
        if action_type == "get_daily_summary":
            return (["2026-02-12 の活動概要を取得しました。"], [], [])
        if action_type == "create_custom_task":
            return (["カスタムタスク「歯医者」を追加しました。"], [], ["item_custom_42"])
        return ([], ["unexpected action"], [])

    class _FakeSummaryClient:
        def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="最終返信です。"))]
            )

    monkeypatch.setattr(app_module, "_build_scheduler_context", lambda *_args, **_kwargs: "ctx")
    monkeypatch.setattr(app_module, "call_scheduler_llm", _fake_call_scheduler_llm)
    monkeypatch.setattr(app_module, "_apply_actions", _fake_apply_actions)
    monkeypatch.setattr(app_module, "UnifiedClient", _FakeSummaryClient)

    result = app_module.process_chat_request(
        db,
        [{"role": "user", "content": "予定確認して追加して最後にもう一度確認して"}],
        save_history=False,
    )

    assert result["reply"] == "最終返信です。"
    assert result["should_refresh"] is True
    assert result["modified_ids"] == ["item_custom_42"]
    assert isinstance(result.get("execution_trace"), list)
    assert len(result.get("execution_trace", [])) == 2
    assert result["execution_trace"][0]["actions"][0]["type"] == "get_daily_summary"
    assert len(apply_calls) == 2
    assert len(llm_calls) == 3
    assert any(
        msg.get("role") == "system" and "Execution round 1 completed." in msg.get("content", "")
        for msg in llm_calls[1]["messages"]
    )


def test_run_scheduler_multi_step_stops_duplicate_actions(monkeypatch):
    db = _FakeSession()
    apply_count = {"value": 0}

    monkeypatch.setattr(app_module, "_build_scheduler_context", lambda *_args, **_kwargs: "ctx")
    monkeypatch.setattr(
        app_module,
        "call_scheduler_llm",
        lambda *_args, **_kwargs: (
            "同じアクションを実行します。",
            [{"type": "create_custom_task", "name": "重複", "date": "2026-02-12", "time": "09:00"}],
        ),
    )

    def _fake_apply_actions(_db, _actions, _today):
        apply_count["value"] += 1
        return (["追加しました。"], [], ["item_custom_1"])

    monkeypatch.setattr(app_module, "_apply_actions", _fake_apply_actions)

    execution = app_module._run_scheduler_multi_step(
        db,
        [{"role": "user", "content": "同じ予定を追加して"}],
        datetime.date(2026, 2, 12),
        max_rounds=4,
    )

    assert apply_count["value"] == 1
    assert execution["modified_ids"] == ["item_custom_1"]
    assert isinstance(execution.get("execution_trace"), list)
    assert len(execution.get("execution_trace", [])) == 1
    assert any("重複実行を停止" in err for err in execution["errors"])
