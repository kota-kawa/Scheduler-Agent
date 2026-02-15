"""LLM orchestration and chat processing service."""

from __future__ import annotations

import datetime
import json
import re
from typing import Any, Dict, List, Union

from sqlmodel import Session

from llm_client import call_scheduler_llm
from scheduler_agent.core.config import get_max_action_rounds, get_max_same_read_action_streak
from scheduler_agent.models import ChatHistory
from scheduler_agent.services.action_service import READ_ONLY_ACTION_TYPES, _apply_actions
from scheduler_agent.services.reply_service import (
    _attach_execution_trace_to_stored_content,
    _build_final_reply,
)
from scheduler_agent.services.schedule_parser_service import (
    _extract_relative_week_shift,
    _extract_weekday,
    _normalize_hhmm,
    _parse_date,
    _resolve_schedule_expression,
    _try_parse_iso_date,
    _week_bounds,
)
from scheduler_agent.services.timeline_service import _build_scheduler_context


_REFERENCE_DATE_TOKENS = (
    "その",
    "それ",
    "同日",
    "当日",
    "同じ日",
    "その日",
    "翌日",
    "翌々日",
    "前日",
    "前々日",
)


def _has_reference_date_token(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    return any(token in text for token in _REFERENCE_DATE_TOKENS)


def _action_signature(actions: List[Dict[str, Any]]) -> str:
    signatures: List[str] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        try:
            signatures.append(json.dumps(action, ensure_ascii=False, sort_keys=True))
        except TypeError:
            signatures.append(str(action))
    return "|".join(signatures)


def _action_fingerprint(action: Dict[str, Any]) -> str:
    if not isinstance(action, dict):
        return ""
    try:
        return json.dumps(action, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(action)


def _dedupe_modified_ids(modified_ids: List[Any]) -> List[str]:
    unique: List[str] = []
    seen: set[str] = set()
    for item in modified_ids:
        if not isinstance(item, str):
            continue
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def _get_last_user_message_from_messages(formatted_messages: List[Dict[str, str]]) -> str:
    for message in reversed(formatted_messages or []):
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content", "")
            return content if isinstance(content, str) else str(content)
    return ""


def _is_week_scope_confirmation_request(user_message: str) -> bool:
    if not isinstance(user_message, str):
        return False
    text = user_message.strip()
    if not text:
        return False
    if _extract_relative_week_shift(text) is None:
        return False
    if _extract_weekday(text) is not None:
        return False

    schedule_tokens = ["予定", "スケジュール", "タスク", "日程"]
    confirm_patterns = [
        r"確認",
        r"見せ",
        r"教えて",
        r"一覧",
        r"表示",
        r"把握",
        r"知りたい",
        r"ある\??$",
        r"あります\??$",
        r"入って",
    ]
    has_schedule = any(token in text for token in schedule_tokens)
    has_confirm = any(re.search(pattern, text) for pattern in confirm_patterns)
    return has_schedule and has_confirm


def _normalize_actions_for_week_scope_confirmation(
    actions: List[Dict[str, Any]],
    user_message: str,
) -> List[Dict[str, Any]]:
    if not _is_week_scope_confirmation_request(user_message):
        return actions

    normalized: List[Dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, dict):
            normalized.append(action)
            continue

        action_type = str(action.get("type", ""))
        if action_type == "get_daily_summary":
            target_date = _try_parse_iso_date(action.get("date"))
            if target_date is None:
                normalized.append(action)
                continue
            week_start, week_end = _week_bounds(target_date)
            normalized.append(
                {
                    "type": "list_tasks_in_period",
                    "start_date": week_start.isoformat(),
                    "end_date": week_end.isoformat(),
                }
            )
            continue

        if action_type == "list_tasks_in_period":
            start_date = _try_parse_iso_date(action.get("start_date"))
            end_date = _try_parse_iso_date(action.get("end_date"))
            if start_date is None or end_date is None:
                normalized.append(action)
                continue
            if start_date == end_date or (start_date <= end_date and (end_date - start_date).days < 6):
                week_start, week_end = _week_bounds(start_date)
                updated = dict(action)
                updated["start_date"] = week_start.isoformat()
                updated["end_date"] = week_end.isoformat()
                normalized.append(updated)
            else:
                normalized.append(action)
            continue

        normalized.append(action)

    return normalized


def _inject_base_date_for_reference_resolves(
    actions: List[Dict[str, Any]],
    resolved_memory: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    last_resolved_date: datetime.date | None = None
    for item in reversed(resolved_memory or []):
        if not isinstance(item, dict):
            continue
        parsed = _try_parse_iso_date(item.get("date"))
        if parsed is not None:
            last_resolved_date = parsed
            break

    if last_resolved_date is None:
        return actions

    normalized: List[Dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, dict):
            normalized.append(action)
            continue
        if str(action.get("type", "")) != "resolve_schedule_expression":
            normalized.append(action)
            continue
        expression = action.get("expression")
        if not _has_reference_date_token(expression):
            normalized.append(action)
            continue
        base_date_value = action.get("base_date")
        if _try_parse_iso_date(base_date_value) is not None:
            normalized.append(action)
            continue

        updated = dict(action)
        updated["base_date"] = last_resolved_date.isoformat()
        normalized.append(updated)

        fallback_base_time = datetime.datetime.now().strftime("%H:%M")
        base_time_value = _normalize_hhmm(updated.get("base_time"), fallback_base_time)
        default_time_value = _normalize_hhmm(updated.get("default_time"), base_time_value)
        calc = _resolve_schedule_expression(
            expression=str(expression or ""),
            base_date=last_resolved_date,
            base_time=base_time_value,
            default_time=default_time_value,
        )
        if not calc.get("ok"):
            continue
        resolved_date = _try_parse_iso_date(calc.get("date"))
        if resolved_date is not None:
            last_resolved_date = resolved_date

    return normalized


def _infer_requested_steps(user_message: str) -> List[Dict[str, Any]]:
    if not isinstance(user_message, str) or not user_message.strip():
        return []

    events: List[tuple[int, str]] = []
    step_patterns: List[tuple[str, str]] = [
        ("confirm", r"(確認|見せて|見せる|一覧|表示|サマリー)"),
        ("add", r"(追加|入れて|登録)"),
        ("complete", r"(完了に|完了して|終わったら|チェックして)"),
        ("append_log", r"(日報.*追記|追記.*日報|日報.*メモ|メモ.*日報)"),
        ("reschedule", r"(ずらして|後ろに|前倒し|時間.*変更|時刻.*変更)"),
    ]

    for step_id, pattern in step_patterns:
        for match in re.finditer(pattern, user_message):
            events.append((match.start(), step_id))

    from scheduler_agent.services.schedule_parser_service import _is_relative_datetime_text

    if _is_relative_datetime_text(user_message):
        events.append((0, "calculate"))

    if not events:
        return []

    events.sort(key=lambda item: item[0])

    step_definitions: Dict[str, Dict[str, Any]] = {
        "calculate": {
            "label": "日時計算",
            "action_types": {"resolve_schedule_expression"},
        },
        "confirm": {
            "label": "予定確認",
            "action_types": {"list_tasks_in_period", "get_daily_summary", "get_day_log"},
        },
        "add": {
            "label": "予定追加",
            "action_types": {"create_custom_task", "add_routine", "add_step"},
        },
        "complete": {
            "label": "完了更新",
            "action_types": {"toggle_custom_task", "toggle_step"},
        },
        "append_log": {
            "label": "日報更新",
            "action_types": {"append_day_log", "update_log"},
        },
        "reschedule": {
            "label": "時刻変更",
            "action_types": {"update_custom_task_time", "update_step_time"},
        },
    }

    steps: List[Dict[str, Any]] = []
    for _, step_id in events:
        definition = step_definitions.get(step_id)
        if not definition:
            continue
        if steps and steps[-1].get("id") == step_id:
            continue
        steps.append(
            {
                "id": step_id,
                "label": definition["label"],
                "action_types": set(definition["action_types"]),
            }
        )
    return steps


def _format_step_progress(steps: List[Dict[str, Any]], completed_steps: int) -> str:
    if not steps:
        return "(none)"

    lines: List[str] = []
    next_step_label = ""
    for idx, step in enumerate(steps, start=1):
        done = idx <= completed_steps
        marker = "x" if done else " "
        label = step.get("label", step.get("id", "step"))
        lines.append(f"- [{marker}] {idx}. {label}")
        if not done and not next_step_label:
            next_step_label = str(label)

    if next_step_label:
        lines.append(f"next_expected_step: {next_step_label}")
    else:
        lines.append("next_expected_step: (all completed)")

    return "\n".join(lines)


def _extract_resolved_memory_from_actions(
    actions: List[Dict[str, Any]],
    default_date: datetime.date,
) -> List[Dict[str, str]]:
    memories: List[Dict[str, str]] = []
    fallback_base_time = datetime.datetime.now().strftime("%H:%M")
    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("type") != "resolve_schedule_expression":
            continue
        expression = action.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            continue
        base_date_value = _parse_date(action.get("base_date"), default_date)
        base_time_value = _normalize_hhmm(action.get("base_time"), fallback_base_time)
        default_time_value = _normalize_hhmm(action.get("default_time"), base_time_value)
        calc = _resolve_schedule_expression(
            expression=expression,
            base_date=base_date_value,
            base_time=base_time_value,
            default_time=default_time_value,
        )
        if not calc.get("ok"):
            continue
        memories.append(
            {
                "expression": expression.strip(),
                "date": str(calc.get("date", "")),
                "time": str(calc.get("time", "")),
                "datetime": str(calc.get("datetime", "")),
                "period_start": str(calc.get("period_start", "")),
                "period_end": str(calc.get("period_end", "")),
            }
        )
    return memories


def _build_round_feedback(
    round_index: int,
    actions: List[Dict[str, Any]],
    results: List[str],
    errors: List[str],
    inferred_steps: List[Dict[str, Any]] | None = None,
    completed_steps: int = 0,
    resolved_memory: List[Dict[str, str]] | None = None,
    duplicate_warning: str = "",
) -> str:
    action_lines = "\n".join(
        f"- {json.dumps(action, ensure_ascii=False, sort_keys=True)}" for action in actions
    ) or "- (none)"
    result_lines = "\n".join(f"- {item}" for item in results) or "- (none)"
    error_lines = "\n".join(f"- {item}" for item in errors) or "- (none)"
    progress_lines = _format_step_progress(inferred_steps or [], completed_steps)
    resolved_lines = "\n".join(
        "- expression="
        f"{item.get('expression')} => date={item.get('date')} "
        f"time={item.get('time')} datetime={item.get('datetime')} "
        f"period_start={item.get('period_start', '')} period_end={item.get('period_end', '')}"
        for item in (resolved_memory or [])[-3:]
    ) or "- (none)"
    duplicate_lines = f"duplicate_warning:\n- {duplicate_warning}\n" if duplicate_warning else ""

    return (
        f"Execution round {round_index} completed.\n"
        "inferred_request_progress:\n"
        f"{progress_lines}\n"
        "resolved_datetime_memory:\n"
        f"{resolved_lines}\n"
        f"{duplicate_lines}"
        "executed_actions:\n"
        f"{action_lines}\n"
        "execution_results:\n"
        f"{result_lines}\n"
        "execution_errors:\n"
        f"{error_lines}\n"
        "元のユーザー要望を満たすために追加操作が必要ならツールを続けて呼んでください。\n"
        "要望が満たされた場合はツールを呼ばず、自然な日本語の最終回答のみを返してください。\n"
        "今日以外の日付を扱う場合（相対表現・曜日指定・明示日付を含む）は resolve_schedule_expression を先に実行してから参照/更新ツールを呼んでください。\n"
        "resolve_schedule_expression が「日付表現を解釈できませんでした」を返した場合は、同じ expression を繰り返さず、記念日名や曖昧語を具体的な月日/ISO日付へ言い換えて再計算してください。\n"
        "「その3日後」「その翌日」など参照語つき日時は、resolved_datetime_memory の直近 date を base_date に設定して計算してください。\n"
        "直前と同じ参照/計算アクションを繰り返さず、next_expected_step を優先してください。\n"
        "同じ作成・更新系のアクションを重複して実行しないでください。"
    )


def _run_scheduler_multi_step(
    db: Session,
    formatted_messages: List[Dict[str, str]],
    today: datetime.date,
    max_rounds: int | None = None,
) -> Dict[str, Any]:
    rounds_limit = max_rounds if isinstance(max_rounds, int) and max_rounds > 0 else get_max_action_rounds()
    working_messages = list(formatted_messages)
    user_message = _get_last_user_message_from_messages(formatted_messages)
    inferred_steps = _infer_requested_steps(user_message)

    all_actions: List[Dict[str, Any]] = []
    all_results: List[str] = []
    all_errors: List[str] = []
    all_modified_ids: List[str] = []
    raw_replies: List[str] = []
    execution_trace: List[Dict[str, Any]] = []
    resolved_memory: List[Dict[str, str]] = []

    previous_signature = ""
    previous_round_had_write = False
    stale_read_repeat_count = 0
    no_progress_rounds = 0
    completed_steps = 0
    executed_write_fingerprints: set[str] = set()
    max_same_read_action_streak = get_max_same_read_action_streak()

    if inferred_steps:
        planning_message = (
            "requested_steps_plan:\n"
            f"{_format_step_progress(inferred_steps, completed_steps)}\n"
            "この順序を意識して実行してください。"
        )
        working_messages = [*working_messages, {"role": "system", "content": planning_message}]

    for round_index in range(1, rounds_limit + 1):
        context = _build_scheduler_context(db, today)

        try:
            reply_text, actions = call_scheduler_llm(working_messages, context)
        except Exception as exc:
            all_errors.append(f"LLM 呼び出しに失敗しました: {exc}")
            break

        reply_text = reply_text or ""
        raw_replies.append(reply_text)

        current_actions = [a for a in actions if isinstance(a, dict)] if isinstance(actions, list) else []
        current_actions = _normalize_actions_for_week_scope_confirmation(current_actions, user_message)
        current_actions = _inject_base_date_for_reference_resolves(current_actions, resolved_memory)
        if not current_actions:
            break

        current_action_types = [
            str(action.get("type", "")) for action in current_actions if isinstance(action, dict)
        ]
        all_read_only = bool(current_action_types) and all(
            action_type in READ_ONLY_ACTION_TYPES for action_type in current_action_types
        )
        signature = _action_signature(current_actions)
        if signature and signature == previous_signature:
            if all_read_only and not previous_round_had_write:
                stale_read_repeat_count += 1
                if stale_read_repeat_count >= max_same_read_action_streak:
                    all_errors.append(
                        f"同じ参照/計算アクションが{max_same_read_action_streak}回連続したため処理を終了しました。"
                    )
                    break
            else:
                all_errors.append("同一アクションが連続して提案されたため、重複実行を停止しました。")
                break
        else:
            stale_read_repeat_count = 0

        previous_signature = signature

        actions_to_execute: List[Dict[str, Any]] = []
        skipped_write_duplicates: List[Dict[str, Any]] = []
        for action in current_actions:
            action_type = str(action.get("type", ""))
            if action_type in READ_ONLY_ACTION_TYPES:
                actions_to_execute.append(action)
                continue
            fingerprint = _action_fingerprint(action)
            if fingerprint and fingerprint in executed_write_fingerprints:
                skipped_write_duplicates.append(action)
                continue
            if fingerprint:
                executed_write_fingerprints.add(fingerprint)
            actions_to_execute.append(action)

        duplicate_warning = ""
        if skipped_write_duplicates:
            duplicate_warning = "同一の更新アクションが再提案されたため再実行をスキップしました。"

        if not actions_to_execute:
            no_progress_rounds += 1
            trace_actions = []
            for action in current_actions:
                action_type = action.get("type") if isinstance(action, dict) else None
                params = {}
                if isinstance(action, dict):
                    params = {k: v for k, v in action.items() if k != "type"}
                trace_actions.append(
                    {
                        "type": str(action_type or "unknown"),
                        "params": params,
                    }
                )
            execution_trace.append(
                {
                    "round": round_index,
                    "actions": trace_actions,
                    "results": [],
                    "errors": [duplicate_warning] if duplicate_warning else [],
                    "skipped": True,
                }
            )
            feedback = _build_round_feedback(
                round_index,
                current_actions,
                [],
                [],
                inferred_steps=inferred_steps,
                completed_steps=completed_steps,
                resolved_memory=resolved_memory,
                duplicate_warning=duplicate_warning,
            )
            assistant_feedback = reply_text.strip() or "了解しました。"
            working_messages = [
                *working_messages,
                {"role": "assistant", "content": assistant_feedback},
                {"role": "system", "content": feedback},
            ]
            if no_progress_rounds >= 2:
                all_errors.append("進捗が得られない状態が続いたため処理を終了しました。")
                break
            continue

        results, errors, modified_ids = _apply_actions(db, actions_to_execute, today)
        all_actions.extend(actions_to_execute)
        all_results.extend(results)
        all_errors.extend(errors)
        all_modified_ids.extend(modified_ids)

        before_completed_steps = completed_steps
        for action in actions_to_execute:
            action_type = str(action.get("type", ""))
            if completed_steps >= len(inferred_steps):
                break
            expected_types = inferred_steps[completed_steps].get("action_types", set())
            if action_type in expected_types:
                completed_steps += 1

        new_resolved_items = _extract_resolved_memory_from_actions(actions_to_execute, today)
        existing_keys = {
            (item.get("expression", ""), item.get("date", ""), item.get("time", ""))
            for item in resolved_memory
        }
        for item in new_resolved_items:
            key = (item.get("expression", ""), item.get("date", ""), item.get("time", ""))
            if key in existing_keys:
                continue
            existing_keys.add(key)
            resolved_memory.append(item)

        trace_actions = []
        for action in actions_to_execute:
            action_type = action.get("type") if isinstance(action, dict) else None
            params = {}
            if isinstance(action, dict):
                params = {k: v for k, v in action.items() if k != "type"}
            trace_actions.append(
                {
                    "type": str(action_type or "unknown"),
                    "params": params,
                }
            )
        execution_trace.append(
            {
                "round": round_index,
                "actions": trace_actions,
                "results": list(results),
                "errors": list(errors),
            }
        )

        has_progress = bool(modified_ids) or bool(results) or completed_steps > before_completed_steps
        if has_progress:
            no_progress_rounds = 0
        else:
            no_progress_rounds += 1

        previous_round_had_write = any(
            str(action.get("type", "")) not in READ_ONLY_ACTION_TYPES for action in actions_to_execute
        )

        feedback = _build_round_feedback(
            round_index,
            actions_to_execute,
            results,
            errors,
            inferred_steps=inferred_steps,
            completed_steps=completed_steps,
            resolved_memory=resolved_memory,
            duplicate_warning=duplicate_warning,
        )
        assistant_feedback = reply_text.strip() or "了解しました。"
        working_messages = [
            *working_messages,
            {"role": "assistant", "content": assistant_feedback},
            {"role": "system", "content": feedback},
        ]

        if no_progress_rounds >= 2:
            all_errors.append("進捗が得られない状態が続いたため処理を終了しました。")
            break
    else:
        all_errors.append(f"複数ステップ実行の上限（{rounds_limit}ラウンド）に達したため処理を終了しました。")

    return {
        "reply_text": raw_replies[-1] if raw_replies else "",
        "raw_replies": raw_replies,
        "actions": all_actions,
        "results": all_results,
        "errors": all_errors,
        "modified_ids": _dedupe_modified_ids(all_modified_ids),
        "execution_trace": execution_trace,
    }


def process_chat_request(
    db: Session, message_or_history: Union[str, List[Dict[str, str]]], save_history: bool = True
) -> Dict[str, Any]:
    formatted_messages = []
    user_message = ""

    if isinstance(message_or_history, str):
        user_message = message_or_history
        formatted_messages = [{"role": "user", "content": user_message}]
    else:
        formatted_messages = message_or_history
        if formatted_messages and formatted_messages[-1].get("role") == "user":
            user_message = formatted_messages[-1].get("content", "")
        else:
            user_message = "(Context only)"

    if save_history:
        try:
            db.add(ChatHistory(role="user", content=user_message))
            db.commit()
        except Exception as exc:
            db.rollback()
            print(f"Failed to save user message: {exc}")

    today = datetime.date.today()
    execution = _run_scheduler_multi_step(db, formatted_messages, today)
    final_reply = _build_final_reply(
        user_message=user_message,
        reply_text=execution.get("reply_text", ""),
        results=execution.get("results", []),
        errors=execution.get("errors", []),
    )

    if save_history:
        try:
            stored_assistant_content = _attach_execution_trace_to_stored_content(
                final_reply,
                execution.get("execution_trace", []),
            )
            db.add(ChatHistory(role="assistant", content=stored_assistant_content))
            db.commit()
        except Exception as exc:
            db.rollback()
            print(f"Failed to save assistant message: {exc}")

    results = execution.get("results", [])
    return {
        "reply": final_reply,
        "should_refresh": (len(results) > 0),
        "modified_ids": execution.get("modified_ids", []),
        "execution_trace": execution.get("execution_trace", []),
    }


__all__ = [
    "_run_scheduler_multi_step",
    "process_chat_request",
]
