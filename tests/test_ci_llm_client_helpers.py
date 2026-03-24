import json
from types import SimpleNamespace

import llm_client


def test_content_to_text_normalizes_multiple_shapes():
    assert llm_client._content_to_text("hello") == "hello"
    assert llm_client._content_to_text(SimpleNamespace(text="world")) == "world"
    assert (
        llm_client._content_to_text(
            [
                {"text": "alpha"},
                SimpleNamespace(text="beta"),
                "gamma",
            ]
        )
        == "alpha\nbeta\ngamma"
    )
    assert llm_client._content_to_text({"content": "delta"}) == "delta"


def test_extract_json_dict_handles_fenced_json():
    parsed = llm_client._extract_json_dict(
        """```json
        {"violation": 1, "category": "Direct Override"}
        ```"""
    )

    assert parsed["violation"] == 1
    assert parsed["category"] == "Direct Override"


def test_extract_actions_from_tool_calls_returns_actions_and_decision():
    tool_calls = [
        SimpleNamespace(
            function=SimpleNamespace(
                name="create_custom_task",
                arguments=json.dumps({"name": "Dentist", "date": "2026-02-12", "time": "09:00"}),
            )
        ),
        SimpleNamespace(
            function=SimpleNamespace(
                name=llm_client.REVIEW_DECISION_TOOL_NAME,
                arguments=json.dumps(
                    {
                        "action_required": True,
                        "should_reply": True,
                        "reply": "done",
                        "notes": "ok",
                    }
                ),
            )
        ),
    ]

    actions, decision = llm_client._extract_actions_from_tool_calls(tool_calls)

    assert actions == [
        {
            "type": "create_custom_task",
            "name": "Dentist",
            "date": "2026-02-12",
            "time": "09:00",
        }
    ]
    assert decision == {
        "action_required": True,
        "should_reply": True,
        "reply": "done",
        "notes": "ok",
    }


def test_extract_actions_from_claude_blocks_returns_reply_and_actions():
    blocks = [
        SimpleNamespace(type="text", text="確認しました。"),
        SimpleNamespace(type="tool_use", name="delete_custom_task", input={"task_id": 5}),
    ]

    reply_text, actions, decision = llm_client._extract_actions_from_claude_blocks(blocks)

    assert reply_text == "確認しました。"
    assert actions == [{"type": "delete_custom_task", "task_id": 5}]
    assert decision is None


def test_claude_messages_from_openai_splits_system_prompt():
    system_prompt, messages = llm_client._claude_messages_from_openai(
        [
            {"role": "system", "content": "system-1"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
    )

    assert system_prompt == "system-1"
    assert messages == [
        {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
    ]


def test_call_scheduler_llm_returns_limit_message_when_quota_exceeded(monkeypatch):
    monkeypatch.setattr(
        llm_client,
        "run_prompt_guard",
        lambda _user_input: {
            "blocked": False,
            "category": None,
            "rationale": None,
            "error": "今月のLLM API利用上限に達しました。",
            "limit_exceeded": True,
            "raw": None,
        },
    )

    reply, actions = llm_client.call_scheduler_llm(
        [{"role": "user", "content": "明日の予定を教えて"}],
        "context",
    )

    assert "上限" in reply
    assert actions == []


def test_call_scheduler_llm_uses_configured_output_token_limit(monkeypatch):
    monkeypatch.setattr(llm_client, "run_prompt_guard", lambda _user_input: {"blocked": False})
    monkeypatch.setattr(llm_client, "get_max_output_tokens", lambda: 5000)
    monkeypatch.setattr(llm_client, "SCHEDULER_TOOLS", [])

    captured: dict = {}

    class _DummyCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content="ok", tool_calls=[]),
                    )
                ]
            )

    class _DummyChat:
        def __init__(self):
            self.completions = _DummyCompletions()

    class _DummyUnifiedClient:
        def __init__(self):
            self.provider = "openai"
            self.model_name = "dummy-model"
            self.chat = _DummyChat()

    monkeypatch.setattr(llm_client, "UnifiedClient", _DummyUnifiedClient)

    reply, actions = llm_client.call_scheduler_llm(
        [{"role": "user", "content": "テスト"}],
        "context",
    )

    assert reply == "ok"
    assert actions == []
    assert captured["max_tokens"] == 5000
