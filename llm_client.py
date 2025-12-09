from __future__ import annotations

import json
import re
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


def _openai_tool_to_anthropic(openai_tool: Dict[str, Any]) -> Dict[str, Any]:
    """Convert OpenAI-style tool definition to Anthropic format."""
    function_def = openai_tool.get("function", {})
    return {
        "name": function_def.get("name"),
        "description": function_def.get("description"),
        "input_schema": function_def.get("parameters"),
    }


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


def _sanitize_text(text: str) -> str:
    """Remove patterns that might confuse the model, like Gemini's function call syntax."""
    if not isinstance(text, str):
        return str(text)
    # Remove <function=...> tags and content if possible, or just break the tag
    # The error showed <function=create_custom_task>{...
    # We'll just replace <function= with (function= to break the syntax detection
    return re.sub(r"<function=", "(function=", text)


def call_scheduler_llm(messages: List[Dict[str, str]], context: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Call the selected LLM with structured tool definitions and return reply/actions."""

    client = UnifiedClient()
    now = datetime.now().astimezone()
    current_time_jp = now.strftime("%Y年%m月%d日 %H時%M分%S秒")
    current_time_iso = now.isoformat(timespec="seconds")

    # Sanitize inputs to prevent hallucination of tool formats
    context = _sanitize_text(context)
    sanitized_messages = []
    for msg in messages:
        sanitized_messages.append({
            "role": msg.get("role"),
            "content": _sanitize_text(msg.get("content", ""))
        })

    base_system_prompt = (
        f"現在日時: {current_time_jp} / {current_time_iso}\n"
        "あなたはユーザーの生活リズムを整え、日々のタスク管理をサポートする、親しみやすく頼れるパートナーAIです。\n"
        "ユーザーの自然言語による指示を解釈し、適切なツールを選択して、ルーチンの管理、カスタムタスク（予定）の操作、日報（Daily Log）の記録を行います。\n"
        "\n"
        "## コンテキストとデータの取り扱い\n"
        "1. **現在のコンテキスト**: 提供されたコンテキストには「今日」のデータ（ルーチン、タスク、ログ）のみが含まれています。\n"
        "2. **日付指定の検索**: 「明日」「来週」「昨日」などのデータが必要な場合は、推測せずに必ず `list_tasks_in_period` や `get_day_log`、`get_daily_summary` を使用して取得してください。\n"
        "3. **IDの厳守**: タスクやステップの完了・削除・編集を行う際は、必ずコンテキストに含まれる `id` (例: `step_id`, `task_id`) を正確に使用してください。\n"
        "    - **新規作成時**: アイテムを新規作成した場合、そのIDは「実行結果」として会話履歴に残ります。直後の操作ではそのIDを参照してください。\n"
        "\n"
        "## ツールの選択基準\n"
        "- **予定・スケジュール**: 外部カレンダーは使用しません。「〇〇の予定を入れて」は `create_custom_task` を使用します。\n"
        "- **習慣・繰り返し**: 「毎週〇曜日に～する」は `add_routine` を使用します。\n"
        "- **日報・メモ**: \n"
        "    - 「日記をつけて」「メモして」など、その日全体の記録は `append_day_log` (追記) を優先的に使用してください。上書きしたい場合のみ `update_log` を使います。\n"
        "    - 特定のタスクに対するメモは `update_custom_task_memo` や `update_step_memo` を使用します。\n"
        "- **完了チェック**: タスクの完了は `toggle_custom_task`、ルーチンのステップは `toggle_step` です。\n"
        "\n"
        "## 応答ガイドライン\n"
        "- **フレンドリーに**: 機械的な応答ではなく、親しみやすい話し言葉（です・ます調）で、適度に絵文字（✨、👍、📅など）を使用してください。\n"
        "- **明確な報告**: ツールを実行した結果は、必ずユーザーに日本語で報告してください。「〇〇を登録しました！」「××を完了にしましたお疲れ様です！」など。\n"
        "- **不明確な指示への対応**: 必要な情報（時間、名前など）が不足している場合は、デフォルト値で強行せず、優しく聞き返してください。ただし日付が省略された場合は「今日」とみなして進めて構いません。\n"
        "- **JSON禁止**: ユーザーへの返答（reply）には生のJSONやツールコール定義を含めず、自然な文章のみを返してください。\n"
    )

    last_exception = None

    for attempt in range(2):
        try:
            current_system_prompt = base_system_prompt
            if attempt > 0:
                current_system_prompt += "\n\nIMPORTANT: Do NOT use '<function=' syntax. Use standard tool calls only."

            prompt_messages: List[Dict[str, str]] = [
                {"role": "system", "content": current_system_prompt},
                {"role": "system", "content": context},
                *sanitized_messages,
            ]

            if client.provider == "claude":
                system_text, claude_messages = _claude_messages_from_openai(prompt_messages)
                
                anthropic_tools = [_openai_tool_to_anthropic(t) for t in SCHEDULER_TOOLS]
                
                response = client.client.messages.create(
                    model=client.model_name,
                    system=system_text,
                    messages=claude_messages,
                    temperature=0.4,
                    max_tokens=1500,
                    tools=anthropic_tools,
                    tool_choice={"type": "auto"},
                )
                reply_text, actions, _ = _extract_actions_from_claude_blocks(getattr(response, "content", None))
                return reply_text or "了解しました。", actions

            response = client.chat.completions.create(
                model=client.model_name,
                messages=prompt_messages,
                temperature=0.4,
                max_tokens=1500,
                tools=SCHEDULER_TOOLS,
                tool_choice="auto",
            )

            message = response.choices[0].message
            reply = _content_to_text(getattr(message, "content", ""))
            actions, _ = _extract_actions_from_tool_calls(getattr(message, "tool_calls", []))

            return reply, actions

        except Exception as e:
            last_exception = e
            err_str = str(e)
            # Check for Anthropic tool_use_failed or similar
            if attempt == 0 and ("tool_use_failed" in err_str or "failed_generation" in err_str or "400" in err_str):
                # Retry with stricter prompt
                continue
            raise e

    if last_exception:
        raise last_exception
    return "エラーが発生しました。", []
