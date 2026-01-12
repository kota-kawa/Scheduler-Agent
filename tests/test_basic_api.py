import asyncio

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
