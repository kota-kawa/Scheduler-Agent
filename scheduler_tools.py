from __future__ import annotations

from typing import Any, Dict, List


def _build_tool(
    # 日本語: OpenAI形式のツール定義を組み立てる / English: Build OpenAI-compatible tool schema
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


# 日本語: レビュー結果ツール名 / English: Tool name for review decision
REVIEW_DECISION_TOOL_NAME = "set_review_outcome"

# ---------- 原子的日付計算ツール ----------
# LLM が日本語を解釈 → 適切な計算ツールを呼び出し → 結果を受け取る → 操作ツールに渡す
_DATE_CALC_TOOLS: List[Dict[str, Any]] = [
    _build_tool(
        "calc_date_offset",
        "基準日からN日後/前の日付を計算します。例: 明日(+1), 明後日(+2), 3日後(+3), 昨日(-1)",
        {
            "base_date": {"type": "string", "description": "基準日 (YYYY-MM-DD)。通常はシステムプロンプトの today_date を指定"},
            "offset_days": {"type": "integer", "description": "日数オフセット（正=後、負=前）"},
        },
        required=["base_date", "offset_days"],
    ),
    _build_tool(
        "calc_month_boundary",
        "指定年月の月初日(start)または月末日(end)を取得します。例: 来月末→(year=来月の年, month=来月, boundary=end)",
        {
            "year": {"type": "integer", "description": "年 (例: 2026)"},
            "month": {"type": "integer", "description": "月 (1-12)"},
            "boundary": {"type": "string", "description": "'start' (月初) または 'end' (月末)"},
        },
        required=["year", "month", "boundary"],
    ),
    _build_tool(
        "calc_nearest_weekday",
        "基準日から最も近い指定曜日を前方/後方に探します。基準日が該当曜日ならその日を返します。例: 来月末の金曜→月末を取得後、backward で金曜を探す",
        {
            "base_date": {"type": "string", "description": "基準日 (YYYY-MM-DD)"},
            "weekday": {"type": "integer", "description": "曜日番号 (0=月, 1=火, 2=水, 3=木, 4=金, 5=土, 6=日)"},
            "direction": {"type": "string", "description": "'forward' (次の該当曜日) または 'backward' (前の該当曜日)"},
        },
        required=["base_date", "weekday", "direction"],
    ),
    _build_tool(
        "calc_week_weekday",
        "N週後/前の指定曜日の日付を計算します。例: 来週火曜(week_offset=1, weekday=1), 再来週金曜(week_offset=2, weekday=4)",
        {
            "base_date": {"type": "string", "description": "基準日 (YYYY-MM-DD)"},
            "week_offset": {"type": "integer", "description": "週オフセット (0=今週, 1=来週, -1=先週, 2=再来週)"},
            "weekday": {"type": "integer", "description": "曜日番号 (0=月, 1=火, 2=水, 3=木, 4=金, 5=土, 6=日)"},
        },
        required=["base_date", "week_offset", "weekday"],
    ),
    _build_tool(
        "calc_week_range",
        "指定日が含まれる週の月曜〜日曜の範囲を返します。「来週の予定」確認時に使用。来週なら base_date に来週の任意の日を指定。",
        {
            "base_date": {"type": "string", "description": "対象週に含まれる任意の日付 (YYYY-MM-DD)"},
        },
        required=["base_date"],
    ),
    _build_tool(
        "calc_time_offset",
        "基準日時から分単位で加減算します。日跨ぎも自動処理。例: 2時間後(+120), 30分前(-30)",
        {
            "base_date": {"type": "string", "description": "基準日 (YYYY-MM-DD)"},
            "base_time": {"type": "string", "description": "基準時刻 (HH:MM)"},
            "offset_minutes": {"type": "integer", "description": "分数オフセット（正=後、負=前）"},
        },
        required=["base_date", "base_time", "offset_minutes"],
    ),
    _build_tool(
        "get_date_info",
        "指定日の曜日等の情報を取得します。曜日の確認や検算に使用。",
        {
            "date": {"type": "string", "description": "対象日 (YYYY-MM-DD)"},
        },
        required=["date"],
    ),
]

# 日本語: スケジューラ向けツール一覧 / English: Tool list for scheduler actions
SCHEDULER_TOOLS: List[Dict[str, Any]] = _DATE_CALC_TOOLS + [
    _build_tool(
        "create_custom_task",
        "日付・時間・名前を指定してカスタムタスク（予定・スケジュール）を追加します。日付は YYYY-MM-DD 形式で指定。today_date 以外の日付は必ず先に計算ツール(calc_*)で算出してから指定してください。",
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
        "ステップの完了状態を更新します。日付が無い場合は today_date を利用してください。today_date 以外の日付は必ず先に計算ツール(calc_*)で算出してから YYYY-MM-DD 形式で指定してください。",
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
        "指定日付の日報（記録・メモ）を上書き保存します。日付が無い場合は today_date を使ってください。today_date 以外の日付は必ず先に計算ツール(calc_*)で算出してください。",
        {
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "content": {"type": "string", "description": "日報本文"},
        },
        required=["content"],
    ),
    _build_tool(
        "append_day_log",
        "指定日付の日報（記録・メモ）に追記します。既存の内容は保持され、新しい内容が改行区切りで追加されます。日付が無い場合は today_date を使ってください。today_date 以外の日付は必ず先に計算ツール(calc_*)で算出してください。",
        {
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "content": {"type": "string", "description": "追記する内容"},
        },
        required=["content"],
    ),
    _build_tool(
        "get_day_log",
        "指定日付の日報（記録・メモ）を取得します。日付が無い場合は today_date を使ってください。today_date 以外の日付は必ず先に計算ツール(calc_*)で算出してください。",
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
        "ルーチンを削除します。routine_id がある場合はそれを優先します。IDが不明な場合は routine_name で削除できます。「すべて」「全部」など全件削除の指示は scope='all' または all=true を指定してください。",
        {
            "routine_id": {"type": "integer", "description": "ルーチンID（分かる場合は最優先）"},
            "routine_name": {"type": "string", "description": "ルーチン名（ID不明時に使用）"},
            "scope": {
                "type": "string",
                "description": "削除範囲。全件削除は 'all'。通常は省略",
            },
            "all": {"type": "boolean", "description": "true の場合はルーチンを全件削除"},
        },
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
        "指定期間のタスク・ルーチンステップ一覧を取得します。日付は YYYY-MM-DD 形式で指定。today_date 以外の日付は必ず先に計算ツール(calc_*)で算出してください。『来週の予定確認』は calc_week_range で週範囲を取得してから使ってください。",
        {
            "start_date": {"type": "string", "description": "YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "YYYY-MM-DD"},
        },
        required=["start_date", "end_date"],
    ),
    _build_tool(
        "get_daily_summary",
        "指定日付のサマリーを生成して返します。日付が無い場合は today_date を利用してください。today_date 以外の日付は必ず先に計算ツール(calc_*)で算出してください。",
        {"date": {"type": "string", "description": "YYYY-MM-DD"}},
    ),
]

# 日本語: レビュー用ツール＋スケジューラツール / English: Review tools plus scheduler tools
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
