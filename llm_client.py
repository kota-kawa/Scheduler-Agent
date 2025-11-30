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


def _extract_json_object(text: Any) -> Tuple[Any | None, str]:
    """Extract the first JSON object from the LLM response text."""

    if text is None:
        return None, ""

    if isinstance(text, dict):
        return text, ""

    if isinstance(text, list):
        joined = "\n".join(_content_to_text(part) for part in text)
        text = joined

    stripped = str(text).strip()
    if stripped.startswith("```json"):
        stripped = stripped[7:]
    if stripped.startswith("```"):
        stripped = stripped[3:]
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    stripped = stripped.strip()

    decoder = json.JSONDecoder()

    try:
        obj, _ = decoder.raw_decode(stripped)
        return obj, stripped
    except json.JSONDecodeError:
        pass

    if "{" in stripped and "}" in stripped:
        snippet = stripped[stripped.find("{") :]
        try:
            obj, _ = decoder.raw_decode(snippet)
            return obj, stripped
        except json.JSONDecodeError:
            return None, stripped

    return None, stripped


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
    """Call the selected LLM with a structured prompt and return reply/actions."""

    client = UnifiedClient()
    now = datetime.now()
    current_time_jp = now.strftime("%Y年%m月%d日 %H時%M分")
    
    system_prompt = (
        f"現在時刻: {current_time_jp}\n"
        "あなたはユーザーのルーチンやカスタムタスク、および日報（Daily Log）を管理するアシスタントです。"
        "提供された context には直近の日報内容（recent_day_logs）も含まれています。"
        "ユーザーが日報の内容について質問した場合は、その情報を参照して回答してください。"
        "必ず次の JSON オブジェクトだけを返してください（コードフェンス禁止）:\n"
        '{"reply":"日本語の返答","actions":[{"type":"create_custom_task","date":"YYYY-MM-DD","name":"タスク名","time":"HH:MM","memo":"任意メモ"},'
        '{"type":"delete_custom_task","task_id":123},'
        '{"type":"toggle_step","date":"YYYY-MM-DD","step_id":123,"done":true,"memo":"任意メモ"},'
        '{"type":"toggle_custom_task","task_id":55,"done":true,"memo":"任意メモ"},'
        '{"type":"update_log","date":"YYYY-MM-DD","content":"日報テキスト"},'
        '{"type":"add_routine","name":"ルーチン名","days":"0,1,2,3,4,5,6","description":"説明"},'
        '{"type":"delete_routine","routine_id":123},'
        '{"type":"add_step","routine_id":123,"name":"ステップ名","time":"HH:MM","category":"Category"},'
        '{"type":"delete_step","step_id":123}]}\n'
        "actions は null か空配列でも構いません。date が無い場合は today_date を使ってください。"
        "context にある ID 以外は使わないでください。reply は日本語の文章のみで JSON を含めないでください。"
    )

    prompt_messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": context},
        *messages,
    ]

    response = client.chat.completions.create(
        model=client.model_name,
        messages=prompt_messages,
        temperature=0.4,
        max_tokens=900,
    )

    message = response.choices[0].message
    content = getattr(message, "content", "")
    parsed, raw = _extract_json_object(content)
    
    if isinstance(parsed, dict):
        reply = parsed.get("reply") if isinstance(parsed.get("reply"), str) else ""
        actions = parsed.get("actions") if isinstance(parsed.get("actions"), list) else []
    else:
        # Fallback: if JSON parsing fails, assume the entire raw text is the reply.
        reply = raw
        actions = []

    return reply, actions
