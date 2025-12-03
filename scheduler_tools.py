from __future__ import annotations

from typing import Any, Dict, List


def _build_tool(
    name: str,
    description: str,
    properties: Dict[str, Any],
    required: List[str] | None = None,
) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


REVIEW_DECISION_TOOL_NAME = "set_review_outcome"

SCHEDULER_TOOLS: List[Dict[str, Any]] = [
    _build_tool(
        "create_custom_task",
        "日付・時間・名前を指定してカスタムタスクを追加します。日付を省略した場合は today_date を使ってください。",
        {
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "name": {"type": "string", "description": "タスク名"},
            "time": {"type": "string", "description": "HH:MM (24時間表記)"},
            "memo": {"type": "string", "description": "任意のメモ"},
        },
        required=["name"],
    ),
    _build_tool(
        "delete_custom_task",
        "指定したIDのカスタムタスクを削除します。",
        {"task_id": {"type": "integer", "description": "カスタムタスクID"}},
        required=["task_id"],
    ),
    _build_tool(
        "toggle_step",
        "ステップの完了状態を更新します。日付が無い場合は today_date を利用してください。",
        {
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "step_id": {"type": "integer", "description": "ステップID"},
            "done": {"type": "boolean", "description": "完了なら true"},
            "memo": {"type": "string", "description": "任意のメモ"},
        },
        required=["step_id"],
    ),
    _build_tool(
        "toggle_custom_task",
        "カスタムタスクの完了状態を更新します。",
        {
            "task_id": {"type": "integer", "description": "カスタムタスクID"},
            "done": {"type": "boolean", "description": "完了なら true"},
            "memo": {"type": "string", "description": "任意のメモ"},
        },
        required=["task_id"],
    ),
    _build_tool(
        "update_custom_task_time",
        "カスタムタスクの予定時刻を変更します。",
        {
            "task_id": {"type": "integer", "description": "カスタムタスクID"},
            "new_time": {"type": "string", "description": "HH:MM (24時間表記)"},
        },
        required=["task_id", "new_time"],
    ),
    _build_tool(
        "rename_custom_task",
        "カスタムタスクの名称を変更します。",
        {
            "task_id": {"type": "integer", "description": "カスタムタスクID"},
            "new_name": {"type": "string", "description": "新しい名称"},
        },
        required=["task_id", "new_name"],
    ),
    _build_tool(
        "update_custom_task_memo",
        "カスタムタスクのメモを更新します。",
        {
            "task_id": {"type": "integer", "description": "カスタムタスクID"},
            "new_memo": {"type": "string", "description": "更新後のメモ（空文字で削除可）"},
        },
        required=["task_id", "new_memo"],
    ),
    _build_tool(
        "update_log",
        "指定日付の日報を上書き保存します。日付が無い場合は today_date を使ってください。",
        {
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "content": {"type": "string", "description": "日報本文"},
        },
        required=["content"],
    ),
    _build_tool(
        "append_day_log",
        "指定日付の日報に追記します。既存の内容は保持され、新しい内容が改行区切りで追加されます。日付が無い場合は today_date を使ってください。",
        {
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "content": {"type": "string", "description": "追記する内容"},
        },
        required=["content"],
    ),
    _build_tool(
        "get_day_log",
        "指定日付の日報を取得します。日付が無い場合は today_date を使ってください。",
        {"date": {"type": "string", "description": "YYYY-MM-DD"}},
    ),
    _build_tool(
        "add_routine",
        "新しいルーチンを追加します。days は 0=月, 6=日 のカンマ区切りです。",
        {
            "name": {"type": "string", "description": "ルーチン名"},
            "days": {"type": "string", "description": "例: 0,1,2,3,4"},
            "description": {"type": "string", "description": "説明/メモ"},
        },
        required=["name"],
    ),
    _build_tool(
        "delete_routine",
        "指定IDのルーチンを削除します。",
        {"routine_id": {"type": "integer", "description": "ルーチンID"}},
        required=["routine_id"],
    ),
    _build_tool(
        "update_routine_days",
        "ルーチンの曜日設定を変更します。days は 0=月, 6=日 のカンマ区切りです。",
        {
            "routine_id": {"type": "integer", "description": "ルーチンID"},
            "new_days": {"type": "string", "description": "例: 0,2,4"},
        },
        required=["routine_id", "new_days"],
    ),
    _build_tool(
        "add_step",
        "ルーチンにステップを追加します。",
        {
            "routine_id": {"type": "integer", "description": "ルーチンID"},
            "name": {"type": "string", "description": "ステップ名"},
            "time": {"type": "string", "description": "HH:MM (24時間表記)"},
            "category": {"type": "string", "description": "カテゴリ (IoT / Browser / Lifestyle / Other)"},
        },
        required=["routine_id", "name"],
    ),
    _build_tool(
        "delete_step",
        "指定IDのステップを削除します。",
        {"step_id": {"type": "integer", "description": "ステップID"}},
        required=["step_id"],
    ),
    _build_tool(
        "update_step_time",
        "ステップの時刻を変更します。",
        {
            "step_id": {"type": "integer", "description": "ステップID"},
            "new_time": {"type": "string", "description": "HH:MM (24時間表記)"},
        },
        required=["step_id", "new_time"],
    ),
    _build_tool(
        "rename_step",
        "ステップ名を変更します。",
        {
            "step_id": {"type": "integer", "description": "ステップID"},
            "new_name": {"type": "string", "description": "新しい名称"},
        },
        required=["step_id", "new_name"],
    ),
    _build_tool(
        "update_step_memo",
        "ステップのメモを更新します。",
        {
            "step_id": {"type": "integer", "description": "ステップID"},
            "new_memo": {"type": "string", "description": "更新後のメモ（空文字で削除可）"},
        },
        required=["step_id", "new_memo"],
    ),
    _build_tool(
        "list_tasks_in_period",
        "指定期間のタスク・ルーチンステップ一覧を取得します。",
        {
            "start_date": {"type": "string", "description": "YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "YYYY-MM-DD"},
        },
        required=["start_date", "end_date"],
    ),
    _build_tool(
        "get_daily_summary",
        "指定日付のサマリーを生成して返します。日付が無い場合は today_date を利用してください。",
        {"date": {"type": "string", "description": "YYYY-MM-DD"}},
    ),
]

REVIEW_TOOLS: List[Dict[str, Any]] = [
    _build_tool(
        REVIEW_DECISION_TOOL_NAME,
        "レビュー結果をまとめます。actions を出す場合は別のツールコールとして発行してください。",
        {
            "action_required": {"type": "boolean", "description": "自動アクションが必要か"},
            "should_reply": {"type": "boolean", "description": "ユーザーへ返信すべきか"},
            "reply": {"type": "string", "description": "返信メッセージ（省略可）"},
            "notes": {"type": "string", "description": "内部メモ/補足"},
        },
        required=["action_required", "should_reply"],
    ),
] + SCHEDULER_TOOLS
