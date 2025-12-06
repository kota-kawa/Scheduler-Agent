from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Tuple
from types import SimpleNamespace

from openai import OpenAI

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

from model_selection import PROVIDER_DEFAULTS, apply_model_selection
from scheduler_tools import REVIEW_DECISION_TOOL_NAME, REVIEW_TOOLS, SCHEDULER_TOOLS


def _content_to_text(content: Any) -> str:
    """Normalize chat completion content into a plain string."""

    if content is None:
        return ""
    if isinstance(content, str):
        return content

    if hasattr(content, "text") and isinstance(content.text, str):
        return content.text

    if isinstance(content, list):
        parts: List[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
                continue
            if hasattr(part, "text") and isinstance(part.text, str):
                parts.append(part.text)
                continue
            if isinstance(part, dict):
                for key in ("text", "data", "content"):
                    value = part.get(key)
                    if isinstance(value, str):
                        parts.append(value)
                        break
        joined = "\n".join(p.strip() for p in parts if isinstance(p, str) and p.strip())
        if joined:
            return joined

    if isinstance(content, dict):
        for key in ("text", "data", "content"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value

    return str(content).strip()


def _safe_json_loads(data: Any) -> Dict[str, Any]:
    if isinstance(data, dict):
        return data
    if not isinstance(data, str):
        return {}
    try:
        parsed = json.loads(data)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _merge_dict(a: Dict[str, Any] | None, b: Dict[str, Any] | None) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    if isinstance(a, dict):
        merged.update(a)
    if isinstance(b, dict):
        merged.update(b)
    return merged


def _claude_messages_from_openai(messages: List[Dict[str, str]]) -> Tuple[str, List[Dict[str, Any]]]:
    """Convert OpenAI-style messages into Anthropic format."""

    system_parts: List[str] = []
    converted: List[Dict[str, Any]] = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "system":
            system_parts.append(str(content))
            continue
        if role not in {"user", "assistant"}:
            continue
        converted.append(
            {
                "role": role,
                "content": [{"type": "text", "text": str(content)}],
            }
        )

    system_prompt = "\n".join(part for part in system_parts if part.strip())
    return system_prompt, converted


def _extract_actions_from_tool_calls(tool_calls: Any) -> Tuple[List[Dict[str, Any]], Dict[str, Any] | None]:
    """Convert OpenAI-style tool_calls into action payloads and optional review decision."""

    actions: List[Dict[str, Any]] = []
    decision: Dict[str, Any] | None = None

    if not tool_calls:
        return actions, decision

    for call in tool_calls:
        function = getattr(call, "function", None)
        name = getattr(function, "name", None)
        raw_args = getattr(function, "arguments", None)
        args = _safe_json_loads(raw_args)

        if name == REVIEW_DECISION_TOOL_NAME:
            decision = {
                "action_required": bool(args.get("action_required")),
                "should_reply": bool(args.get("should_reply")),
                "reply": args.get("reply") or "",
                "notes": args.get("notes") or "",
            }
            continue

        if not name:
            continue

        payload = {"type": name}
        if isinstance(args, dict):
            payload.update({k: v for k, v in args.items() if v is not None})
        actions.append(payload)

    return actions, decision


def _extract_actions_from_claude_blocks(blocks: Any) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any] | None]:
    """Parse Anthropic content blocks into reply text, actions, and optional review decision."""

    reply_parts: List[str] = []
    actions: List[Dict[str, Any]] = []
    decision: Dict[str, Any] | None = None

    if not isinstance(blocks, list):
        return "", actions, decision

    for block in blocks:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            reply_parts.append(getattr(block, "text", ""))
        elif block_type == "tool_use":
            name = getattr(block, "name", None)
            args = getattr(block, "input", {}) if hasattr(block, "input") else {}
            if name == REVIEW_DECISION_TOOL_NAME:
                decision = {
                    "action_required": bool(args.get("action_required")),
                    "should_reply": bool(args.get("should_reply")),
                    "reply": args.get("reply") or "",
                    "notes": args.get("notes") or "",
                }
                continue
            if not name or not isinstance(args, dict):
                continue
            payload = {"type": name}
            payload.update({k: v for k, v in args.items() if v is not None})
            actions.append(payload)

    return "\n".join(part for part in reply_parts if part.strip()), actions, decision


class UnifiedClient:
    """Provider-agnostic chat client aligned with IoT-Agent's selection logic."""

    def __init__(self):
        provider, model_name, base_url, api_key = apply_model_selection("scheduler")

        if not api_key:
            provider_meta = PROVIDER_DEFAULTS.get(provider, {})
            expected_key = provider_meta.get("api_key_env", "OPENAI_API_KEY")
            raise RuntimeError(
                f"API key for provider '{provider}' is not set. Please set '{expected_key}' in your secrets.env file."
            )

        self.provider = provider
        self.model_name = model_name
        self.base_url = base_url
        self.api_key = api_key

        if self.provider == "claude":
            if Anthropic is None:
                raise ImportError("Anthropic SDK is not installed. Please run `pip install anthropic`.")
            self.client = Anthropic(api_key=self.api_key)
        else:
            client_kwargs: Dict[str, Any] = {"api_key": self.api_key}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            if self.provider == "gemini":
                client_kwargs["default_headers"] = {"x-goog-api-key": self.api_key}
            self.client = OpenAI(**client_kwargs)

        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        if self.provider == "claude":
            return self._create_anthropic(**kwargs)

        # OpenAI-compatible handling
        # Pre-emptive fix for o1 models which don't support temperature
        model_name = kwargs.get("model", self.model_name)
        if str(model_name).lower().startswith("o1-"):
            kwargs.pop("temperature", None)

        # Iterative retry logic for parameter incompatibilities
        # We allow up to 3 attempts to automatically fix common issues (e.g. temp, max_tokens)
        last_exception = None
        for _ in range(3):
            try:
                return self.client.chat.completions.create(**kwargs)
            except Exception as e:
                last_exception = e
                err_str = str(e).lower()
                fixed = False

                # Handle "Unsupported value: 'temperature'..." or similar
                # o1 models often strictly enforce temperature=1 or no temperature param
                if "temperature" in err_str and ("unsupported" in err_str or "invalid" in err_str or "not supported" in err_str):
                    if "temperature" in kwargs:
                        kwargs.pop("temperature")
                        fixed = True

                # Handle "Unsupported parameter: 'max_tokens'" or similar
                # o1 models and newer OpenAI versions require max_completion_tokens
                if "max_tokens" in err_str and ("unsupported" in err_str or "parameter" in err_str or "unknown" in err_str):
                    if "max_tokens" in kwargs:
                        kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
                        fixed = True

                if not fixed:
                    raise last_exception

        if last_exception:
            raise last_exception

    def _create_anthropic(self, **kwargs):
        model = kwargs.get("model", self.model_name)
        messages = kwargs.get("messages", [])

        system_prompt = ""
        filtered_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                system_prompt += msg.get("content", "") + "\n"
            else:
                filtered_messages.append(msg)

        max_tokens = kwargs.get("max_tokens", 1024)
        temperature = kwargs.get("temperature", 0.4)

        response = self.client.messages.create(
            model=model,
            system=system_prompt.strip(),
            messages=filtered_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        content = response.content[0].text if response.content else ""

        message = SimpleNamespace(content=content, parsed=None)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


def _current_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def call_scheduler_llm(messages: List[Dict[str, str]], context: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Call the selected LLM with structured tool definitions and return reply/actions."""

    client = UnifiedClient()
    now = datetime.now().astimezone()
    current_time_jp = now.strftime("%Y年%m月%d日 %H時%M分%S秒")
    current_time_iso = now.isoformat(timespec="seconds")

    system_prompt = (
        f"現在日時: {current_time_jp} / {current_time_iso}\n"
        "あなたはユーザーのルーチンやカスタムタスク、日報（Daily Log）を管理する親しみやすいアシスタントです。\n"
        "\n"
        "## 基本指針\n"
        "- ユーザーへの応答は、機械的ではなく**フレンドリーに、かつ簡潔で分かりやすく**してください。\n"
        "- 必ず提供されたツールを使ってアクションを実行し、結果を日本語で要約してください。\n"
        "- date を省略された場合は context に含まれる today_date を使ってください。\n"
        "- 日付指定が無い依頼は「今日」の扱いで進め、日報やタスクの読み書きも today_date を前提にしてください。日付の確認質問はユーザーが別日を示唆したときのみ行ってください。\n"
        "- 返信は日本語の文章のみで JSON を含めず、ツール呼び出しは必要な分だけにしてください。\n"
        "- ユーザーへの出力は、見やすく、分かりやすく、簡潔で綺麗な形式に整形してください。\n"
        "\n"
        "## エラーハンドリング・確認事項\n"
        "- コンテキスト情報から判断して、指定されたIDのタスクが見つからない場合は、ツールを呼び出さずにその旨を優しく伝えてください。\n"
        "- アクションに必要な情報（例: 新しいタスクの名前、移動先の日付など）が欠けている場合は、勝手に補完せず、ユーザーに詳細を確認してください。ただし日付や時間帯が無いだけのケースでは today_date/未指定のまま進めてください。\n"
        "\n"
        "## 報告フォーマット\n"
        "- 操作成功時: 「〇〇を追加しましたよ！」「××を更新しておきました」のように、完了したことを明るく報告してください。\n"
        "- 操作失敗時: 「〇〇が見つかりませんでした」「〇〇の形式がちょっと違うみたいです」のように、理由を分かりやすく伝えてください。\n"
        "- 複数のアクションを行った場合は、箇条書きなどで見やすく整理してください。\n"
    )

    prompt_messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": context},
        *messages,
    ]

    if client.provider == "claude":
        system_text, claude_messages = _claude_messages_from_openai(prompt_messages)
        response = client.client.messages.create(
            model=client.model_name,
            system=system_text,
            messages=claude_messages,
            temperature=0.4,
            max_tokens=900,
            tools=SCHEDULER_TOOLS,
            tool_choice={"type": "auto"},
        )
        reply_text, actions, _ = _extract_actions_from_claude_blocks(getattr(response, "content", None))
        return reply_text or "了解しました。", actions

    response = client.chat.completions.create(
        model=client.model_name,
        messages=prompt_messages,
        temperature=0.4,
        max_tokens=900,
        tools=SCHEDULER_TOOLS,
        tool_choice="auto",
    )

    message = response.choices[0].message
    reply = _content_to_text(getattr(message, "content", ""))
    actions, _ = _extract_actions_from_tool_calls(getattr(message, "tool_calls", []))

    return reply, actions
