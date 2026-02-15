"""Reply formatting and execution trace helpers."""

from __future__ import annotations

import base64
import json
import re
from typing import Any, Dict, List

from llm_client import UnifiedClient, _content_to_text

from scheduler_agent.core.config import EXEC_TRACE_MARKER_PREFIX, EXEC_TRACE_MARKER_SUFFIX


def _remove_no_schedule_lines(text: str) -> str:
    if not isinstance(text, str):
        return str(text)

    filtered_lines = []
    for line in text.splitlines():
        if re.search(r"予定\s*(?:な\s*し|無し)", line):
            continue
        filtered_lines.append(line)

    cleaned = "\n".join(filtered_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _attach_execution_trace_to_stored_content(
    content: str,
    execution_trace: List[Dict[str, Any]] | None,
) -> str:
    base_content = content if isinstance(content, str) else str(content)
    trace_items = [item for item in (execution_trace or []) if isinstance(item, dict)]
    if not trace_items:
        return base_content

    try:
        trace_json = json.dumps(trace_items, ensure_ascii=False, sort_keys=True)
        encoded = base64.b64encode(trace_json.encode("utf-8")).decode("ascii")
    except Exception:
        return base_content

    return f"{base_content}\n{EXEC_TRACE_MARKER_PREFIX}{encoded}{EXEC_TRACE_MARKER_SUFFIX}"


def _extract_execution_trace_from_stored_content(content: Any) -> tuple[str, List[Dict[str, Any]]]:
    text = content if isinstance(content, str) else str(content or "")
    pattern = re.compile(
        rf"\n?{re.escape(EXEC_TRACE_MARKER_PREFIX)}([A-Za-z0-9+/=]+){re.escape(EXEC_TRACE_MARKER_SUFFIX)}\s*$"
    )
    match = pattern.search(text)
    if not match:
        return text, []

    body = text[: match.start()].rstrip()
    encoded = match.group(1)
    try:
        decoded = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
        parsed = json.loads(decoded)
    except Exception:
        return body, []

    if not isinstance(parsed, list):
        return body, []

    trace = [item for item in parsed if isinstance(item, dict)]
    return body, trace


def _is_internal_system_error(error_text: str) -> bool:
    if not isinstance(error_text, str):
        return False
    text = error_text.strip()
    if not text:
        return False
    internal_markers = [
        "同一アクションが連続して提案されたため、重複実行を停止しました。",
        "同じ参照/計算アクションが続いたため処理を終了しました。",
        "同じ参照/計算アクションが10回連続したため処理を終了しました。",
        "進捗が得られない状態が続いたため処理を終了しました。",
        "複数ステップ実行の上限",
        "同一の更新アクションが再提案されたため再実行をスキップしました。",
    ]
    return any(marker in text for marker in internal_markers)


def _looks_mechanical_reply(text: str) -> bool:
    if not isinstance(text, str):
        return False
    markers = ["【実行結果】", "計算結果:", "expression=", "source=", "datetime="]
    return any(marker in text for marker in markers)


def _friendly_result_line(result: str) -> List[str]:
    if not isinstance(result, str) or not result.strip():
        return []

    text = result.strip()

    calc_match = re.match(
        r"計算結果:\s*expression=(.+?)\s+date=([0-9]{4}-[0-9]{2}-[0-9]{2})\s+time=([0-9]{2}:[0-9]{2})",
        text,
    )
    if calc_match:
        expression = calc_match.group(1).strip()
        date_value = calc_match.group(2)
        time_value = calc_match.group(3)
        return [f"🧮 「{expression}」を {date_value} {time_value} に計算しました！"]

    add_custom_match = re.match(
        r"カスタムタスク「(.+?)」\(ID:\s*\d+\)\s+を\s+([0-9]{4}-[0-9]{2}-[0-9]{2})\s+の\s+([0-9]{2}:[0-9]{2})\s+に追加しました。",
        text,
    )
    if add_custom_match:
        name = add_custom_match.group(1).strip()
        date_value = add_custom_match.group(2)
        time_value = add_custom_match.group(3)
        return [f"📅 {date_value} {time_value} に「{name}」を追加しました！"]

    toggle_custom_match = re.match(r"カスタムタスク「(.+?)」を\s+(完了|未完了)\s+に更新しました。", text)
    if toggle_custom_match:
        name = toggle_custom_match.group(1).strip()
        status = toggle_custom_match.group(2)
        return [f"✅ 「{name}」を{status}にしました。"]

    summary_match = re.match(r"([0-9]{4}-[0-9]{2}-[0-9]{2})\s+の活動概要:", text)
    if summary_match:
        date_value = summary_match.group(1)
        lines = [f"📋 {date_value} の予定を確認しました！"]
        detail_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("- ")]
        readable_details: List[str] = []
        for detail in detail_lines:
            entry_match = re.match(r"-\s*([0-9]{2}:[0-9]{2})\s+(.+?)\s+\((完了|未完了)\)", detail)
            if entry_match:
                readable_details.append(
                    f"・{entry_match.group(1)} {entry_match.group(2)}（{entry_match.group(3)}）"
                )
        if readable_details:
            lines.extend(readable_details[:5])
        else:
            lines.append("・いまのところ目立った予定はありません。")
        return lines

    return [f"・{text}"]


def _build_pop_friendly_reply(
    user_message: str,
    results: List[str],
    errors: List[str],
) -> str:
    lines: List[str] = []
    lines.append("✨ 実行しました！")

    for result in results:
        lines.extend(_friendly_result_line(result))

    visible_errors = [err for err in errors if not _is_internal_system_error(err)]
    if visible_errors:
        lines.append("⚠️ いくつか確認が必要な点があります。")
        lines.extend(f"・{err}" for err in visible_errors[:3])

    if not results and not visible_errors:
        if user_message.strip():
            lines.append("内容を確認しました。必要なら次の操作もすぐ進められます。")
        else:
            lines.append("内容を確認しました。")

    lines.append("🌈 ほかにもやりたい操作があれば続けて教えてください！")
    return _remove_no_schedule_lines("\n".join(lines))


def _build_final_reply(
    user_message: str,
    reply_text: str,
    results: List[str],
    errors: List[str],
) -> str:
    if not results and not errors:
        final_reply = reply_text if reply_text else "了解しました。"
        return _remove_no_schedule_lines(final_reply)

    visible_errors = [err for err in errors if not _is_internal_system_error(err)]
    summary_client = UnifiedClient()

    result_text = ""
    if results:
        result_text += "【実行結果】\n" + "\n".join(f"- {item}" for item in results) + "\n"
    if visible_errors:
        result_text += "【エラー】\n" + "\n".join(f"- {err}" for err in visible_errors) + "\n"

    summary_system_prompt = (
        "あなたはユーザーのスケジュール管理をサポートする親しみやすいAIパートナーです。\n"
        "ユーザーの要望に対してシステムがアクションを実行しました。\n"
        "その「実行結果」をもとに、ユーザーへの最終的な回答を作成してください。\n"
        "\n"
        "## ガイドライン\n"
        "1. **フレンドリーに**: 絵文字（📅, ✅, ✨, 👍など）を適度に使用し、硬苦しくない丁寧語（です・ます）で話してください。\n"
        "2. **分かりやすく**: 実行結果の羅列（「カスタムタスク[2]...」のような形式）は避け、人間が読みやすい文章に整形してください。\n"
        "   - 例: 「12月10日の9時から『カラオケ』の予定が入っていますね！楽しんできてください🎤」\n"
        "   - 予定がない日は `予定なし` と書かず、その行自体を省略してください。\n"
        "   - `expression=...` `source=...` のような内部表現はそのまま出力しないでください。\n"
        "3. **エラーへの対応**: エラーがある場合は、優しくその旨を伝え、どうすればよいか（もし分かれば）示唆してください。\n"
        "   - 重複停止や上限到達などの内部制御メッセージは、必要時だけ『一部を安全のためスキップしました』程度に言い換えてください。\n"
        "4. **元の文脈を維持**: ユーザーの元の発言に対する返答として自然になるようにしてください。\n"
    )

    summary_messages = [
        {"role": "system", "content": summary_system_prompt},
        {"role": "user", "content": f"ユーザーの発言: {user_message}\n\n{result_text}"},
    ]

    try:
        resp = summary_client.create(messages=summary_messages, temperature=0.7, max_tokens=1000)
        final_reply = _content_to_text(resp.choices[0].message.content)
        if _looks_mechanical_reply(final_reply):
            final_reply = _build_pop_friendly_reply(user_message, results, errors)
    except Exception as exc:
        final_reply = _build_pop_friendly_reply(user_message, results, errors)
        print(f"Summary LLM failed: {exc}")

    return _remove_no_schedule_lines(final_reply)


__all__ = [
    "_attach_execution_trace_to_stored_content",
    "_extract_execution_trace_from_stored_content",
    "_build_final_reply",
    "_build_pop_friendly_reply",
    "_remove_no_schedule_lines",
    "_is_internal_system_error",
]
