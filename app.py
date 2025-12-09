import datetime
import calendar
import os
import json
from typing import Any, Dict, List, Union
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from dateutil import parser as date_parser
from dotenv import load_dotenv

load_dotenv("secrets.env")

from llm_client import (
    UnifiedClient,
    _claude_messages_from_openai,
    _content_to_text,
    _extract_actions_from_claude_blocks,
    _extract_actions_from_tool_calls,
    _merge_dict,
    call_scheduler_llm,
)
from model_selection import apply_model_selection, current_available_models, update_override
from scheduler_tools import REVIEW_TOOLS

from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.config['SECRET_KEY'] = 'devkey'
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(app.instance_path, 'scheduler.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

try:
    os.makedirs(app.instance_path)
except OSError:
    pass

db = SQLAlchemy(app)

@app.context_processor
def _inject_proxy_prefix():
    return {"proxy_prefix": request.environ.get("SCRIPT_NAME", "") or ""}

# Models

class Routine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    days = db.Column(db.String(50), default="0,1,2,3,4") # 0=Mon, 6=Sun. Comma separated
    description = db.Column(db.String(200))
    steps = db.relationship('Step', backref='routine', lazy=True, cascade="all, delete-orphan")

class Step(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    routine_id = db.Column(db.Integer, db.ForeignKey('routine.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    time = db.Column(db.String(10), default="00:00") # HH:MM
    category = db.Column(db.String(50), default="Other") # IoT, Browser, Lifestyle, Other
    memo = db.Column(db.String(200)) # New field

class DailyLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    step_id = db.Column(db.Integer, db.ForeignKey('step.id'), nullable=False)
    done = db.Column(db.Boolean, default=False)
    memo = db.Column(db.String(200))
    
    step = db.relationship('Step')

class CustomTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    time = db.Column(db.String(10), default="00:00")
    done = db.Column(db.Boolean, default=False)
    memo = db.Column(db.String(200))

class DayLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    content = db.Column(db.Text)

class ChatHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now)

class EvaluationResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.now)
    model_name = db.Column(db.String(100))
    task_prompt = db.Column(db.Text)
    agent_reply = db.Column(db.Text)
    tool_calls = db.Column(db.Text) # JSON string
    is_success = db.Column(db.Boolean)
    comments = db.Column(db.Text)

# Initialize DB
with app.app_context():
    db.create_all()

# Helpers
def get_weekday_routines(weekday_int):
    all_routines = Routine.query.all()
    matched = []
    for r in all_routines:
        if str(weekday_int) in r.days.split(','):
            matched.append(r)
    return matched

def _parse_date(value, default_date):
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError:
            try:
                return date_parser.parse(value).date()
            except (ValueError, TypeError, OverflowError):
                return default_date
    return default_date

def _bool_from_value(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default

def _get_timeline_data(date_obj):
    routines = get_weekday_routines(date_obj.weekday())
    custom_tasks = CustomTask.query.filter_by(date=date_obj).all()
    
    timeline_items = []
    total_items = 0
    completed_items = 0

    for r in routines:
        for s in r.steps:
            log = DailyLog.query.filter_by(date=date_obj, step_id=s.id).first()
            timeline_items.append({
                'type': 'routine',
                'routine': r,
                'step': s,
                'log': log,
                'time': s.time,
                'id': s.id
            })
            total_items += 1
            if log and log.done:
                completed_items += 1
            
    for ct in custom_tasks:
        timeline_items.append({
            'type': 'custom',
            'routine': {'name': 'Personal'},
            'step': {'name': ct.name, 'category': 'Custom', 'id': ct.id},
            'log': {'done': ct.done, 'memo': ct.memo},
            'time': ct.time,
            'id': ct.id,
            'real_obj': ct
        })
        total_items += 1
        if ct.done:
            completed_items += 1
    
    timeline_items.sort(key=lambda x: x['time'])
    
    completion_rate = 0
    if total_items > 0:
        completion_rate = int((completed_items / total_items) * 100)
        
    return timeline_items, completion_rate

def _build_scheduler_context(today=None):
    today = today or datetime.date.today()
    routines = Routine.query.all()
    today_logs = {log.step_id: log for log in DailyLog.query.filter_by(date=today).all()}
    custom_tasks = CustomTask.query.filter_by(date=today).all()
    
    # Fetch recent DayLogs (Today + past 2 days)
    recent_day_logs = []
    for i in range(3):
        d = today - datetime.timedelta(days=i)
        dl = DayLog.query.filter_by(date=d).first()
        if dl and dl.content:
            recent_day_logs.append(f"Date: {d.isoformat()} | Content: {dl.content}")

    routine_lines = []
    for r in routines:
        days_label = r.days or ""
        steps = ", ".join(
            f"[{s.id}] {s.time} {s.name} ({s.category})"
            for s in sorted(r.steps, key=lambda item: item.time)
        ) or "no steps"
        routine_lines.append(f"- Routine {r.id}: {r.name} | days={days_label} | {steps}")

    custom_lines = []
    for task in sorted(custom_tasks, key=lambda t: t.time):
        memo = f" memo={task.memo}" if task.memo else ""
        custom_lines.append(
            f"- CustomTask {task.id}: {task.time} {task.name} done={task.done}{memo}"
        )

    log_lines = []
    for step_id, log in today_logs.items():
        memo = f" memo={log.memo}" if log.memo else ""
        log_lines.append(f"- StepLog step_id={step_id} done={log.done}{memo}")

    context_parts = [
        f"today_date: {today.isoformat()}",
        "routines:",
        *routine_lines,
        "today_custom_tasks:",
        *(custom_lines or ["(none)"]),
        "today_step_logs:",
        *(log_lines or ["(none)"]),
        "recent_day_logs:",
        *(recent_day_logs or ["(none)"]),
    ]
    return "\n".join(context_parts)


def _format_history_for_prompt(history_messages: List[Dict[str, str]]) -> str:
    """Render conversation history into a compact prompt-friendly text."""

    lines = []
    for entry in history_messages:
        role = entry.get("role")
        content = entry.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            continue
        lines.append(f"{role}: {content.strip()}")
    return "\n".join(lines) or "会話ログは空でした。"


def _normalise_history_messages(raw_history: Any) -> List[Dict[str, str]]:
    """Coerce incoming history payloads into a safe list of role/content pairs."""

    messages: List[Dict[str, str]] = []
    if not isinstance(raw_history, list):
        return messages

    for entry in raw_history:
        if not isinstance(entry, dict):
            continue
        role = str(entry.get("role") or "").strip().lower()
        content = entry.get("content")
        if role not in {"user", "assistant", "system"}:
            continue
        if not isinstance(content, str):
            continue
        messages.append({"role": role, "content": content})
    return messages


def _call_conversation_review(messages: List[Dict[str, str]], context: str) -> Dict[str, Any]:
    """Ask the scheduler LLM to review recent conversation turns and suggest actions."""

    client = UnifiedClient()
    provider = client.provider
    model_name = client.model_name
    now = datetime.datetime.now().astimezone()
    now_text = now.strftime("%Y-%m-%d %H:%M:%S %Z")
    now_iso = now.isoformat(timespec="seconds")
    history_text = _format_history_for_prompt(messages)

    system_prompt = (
        f"現在日時: {now_text} / {now_iso}\n"
        "あなたは「スケジュール・タスク管理専門」のアシスタントです。\n\n"

        "【用語の定義】\n"
        "- 「予定」「スケジュール」→ カスタムタスク (Custom Task)\n"
        "- 「記録」「メモ」→ 日報 (Daily Log)\n\n"
        
        "【あなたの専門分野（発言可能な範囲）】\n"
        "- 予定管理: 予定の追加・変更・削除・確認\n"
        "- タスク管理: ToDoリスト、タスクの進捗管理\n"
        "- 日報・活動記録: 日々の活動ログ、達成事項の記録\n"
        "- リマインダー: 時間ベースの通知設定\n\n"
        
        "【発言してはいけない場合】\n"
        "- Web検索・ブラウザ操作 → Browser Agentの専門\n"
        "- IoTデバイス操作 → IoT Agentの専門\n"
        "- 料理・洗濯・家庭科の知識 → Life-Style Agentの専門\n"
        "- スケジュール/タスクと無関係な話題\n\n"
        
        "【判断ルール】\n"
        "1.  ツール呼び出しは、予定・タスク・日報の操作が「明示的に」必要な場合のみ\n"
        "2. 会話中に日時・予定・タスクのキーワードがあっても、操作依頼でなければ発言しない\n"
        "3. 単なる確認・アドバイスでは発言しない\n\n"
        
        "【発言する例】\n"
        "- 「明日の予定を追加して」→ ツール呼び出し\n"
        "- 「今週のタスクを確認して」→ 発言する\n"
        
        "【発言しない例】\n"
        "- 「明日は暑いらしい」→ 発言しない（天気の話題）\n"
        "- 「夕食のレシピ」→ 発言しない\n"
    )

    prompt_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": context},
        {"role": "user", "content": f"会話ログ:\n{history_text}\n必要があればツールを使って自動対応してください。"},
    ]

    reply_text = ""
    actions: List[Dict[str, Any]] = []
    decision: Dict[str, Any] = {}

    if provider == "claude":
        system_text, claude_messages = _claude_messages_from_openai(prompt_messages)
        response = client.client.messages.create(
            model=model_name,
            system=system_text,
            messages=claude_messages,
            temperature=0.2,
            max_tokens=800,
            tools=REVIEW_TOOLS,
            tool_choice={"type": "auto"},
        )
        reply_text, actions, decision = _extract_actions_from_claude_blocks(getattr(response, "content", None))
    else:
        response = client.chat.completions.create(
            model=model_name,
            messages=prompt_messages,
            temperature=0.2,
            max_tokens=800,
            tools=REVIEW_TOOLS,
            tool_choice="auto",
        )

        message = response.choices[0].message if response and getattr(response, "choices", None) else None
        reply_text = _content_to_text(getattr(message, "content", "")) if message else ""
        actions, decision = _extract_actions_from_tool_calls(getattr(message, "tool_calls", [])) if message else ([], None)
        decision = decision or {}

    resolved = _merge_dict(
        {
            "action_required": bool(actions),
            "should_reply": bool(reply_text),
            "reply": reply_text.strip(),
            "notes": "",
        },
        decision,
    )

    if resolved.get("reply"):
        resolved["should_reply"] = True
    if actions and not resolved.get("action_required"):
        resolved["action_required"] = True

    return {
        "action_required": bool(resolved.get("action_required")),
        "should_reply": bool(resolved.get("should_reply")),
        "reply": resolved.get("reply") or "",
        "actions": actions,
        "notes": resolved.get("notes") or "",
    }

def _apply_actions(actions, default_date):
    results = []
    errors = []
    modified_ids = []
    dirty = False

    if not isinstance(actions, list) or not actions:
        return results, errors, modified_ids

    try:
        for action in actions:
            if not isinstance(action, dict):
                continue
            action_type = action.get("type")

            if action_type == "create_custom_task":
                name = action.get("name")
                if not isinstance(name, str) or not name.strip():
                    errors.append("create_custom_task: name が指定されていません。")
                    continue
                date_value = _parse_date(action.get("date"), default_date)
                time_value = action.get("time") if isinstance(action.get("time"), str) else "00:00"
                memo = action.get("memo") if isinstance(action.get("memo"), str) else ""
                new_task = CustomTask(date=date_value, name=name.strip(), time=time_value.strip(), memo=memo.strip())
                db.session.add(new_task)
                db.session.flush() # Get ID
                results.append(f"カスタムタスク「{new_task.name}」(ID: {new_task.id}) を {date_value} の {new_task.time} に追加しました。")
                modified_ids.append(f"item_custom_{new_task.id}")
                dirty = True
                continue
            
            if action_type == "delete_custom_task":
                task_id = action.get("task_id")
                try:
                    task_id_int = int(task_id)
                except (TypeError, ValueError):
                    errors.append("delete_custom_task: task_id が不正です。")
                    continue
                task_obj = CustomTask.query.get(task_id_int)
                if not task_obj:
                    errors.append(f"task_id={task_id_int} が見つかりませんでした。")
                    continue
                db.session.delete(task_obj)
                results.append(f"カスタムタスク「{task_obj.name}」を削除しました。")
                # No modified ID because it's gone, but we want to refresh
                dirty = True
                continue

            if action_type == "toggle_step":
                step_id = action.get("step_id")
                try:
                    step_id_int = int(step_id)
                except (TypeError, ValueError):
                    errors.append("toggle_step: step_id が不正です。")
                    continue
                step_obj = Step.query.get(step_id_int)
                if not step_obj:
                    errors.append(f"step_id={step_id_int} が見つかりませんでした。")
                    continue
                date_value = _parse_date(action.get("date"), default_date)
                log = DailyLog.query.filter_by(date=date_value, step_id=step_obj.id).first()
                if not log:
                    log = DailyLog(date=date_value, step_id=step_obj.id)
                    db.session.add(log)
                log.done = _bool_from_value(action.get("done"), True)
                memo = action.get("memo")
                if isinstance(memo, str):
                    log.memo = memo.strip()
                results.append(
                    f"ステップ「{step_obj.name}」({date_value}) を {'完了' if log.done else '未完了'} に更新しました。"
                )
                modified_ids.append(f"item_routine_{step_obj.id}")
                dirty = True
                continue

            if action_type == "toggle_custom_task":
                task_id = action.get("task_id")
                try:
                    task_id_int = int(task_id)
                except (TypeError, ValueError):
                    errors.append("toggle_custom_task: task_id が不正です。")
                    continue
                task_obj = CustomTask.query.get(task_id_int)
                if not task_obj:
                    errors.append(f"task_id={task_id_int} が見つかりませんでした。")
                    continue
                task_obj.done = _bool_from_value(action.get("done"), True)
                memo = action.get("memo")
                if isinstance(memo, str):
                    task_obj.memo = memo.strip()
                results.append(
                    f"カスタムタスク「{task_obj.name}」を {'完了' if task_obj.done else '未完了'} に更新しました。"
                )
                modified_ids.append(f"item_custom_{task_obj.id}")
                dirty = True
                continue

            if action_type == "update_custom_task_time":
                task_id = action.get("task_id")
                new_time = action.get("new_time")
                if not new_time:
                    errors.append("update_custom_task_time: new_time が指定されていません。")
                    continue
                try:
                    task_id_int = int(task_id)
                except (TypeError, ValueError):
                    errors.append("update_custom_task_time: task_id が不正です。")
                    continue
                task_obj = CustomTask.query.get(task_id_int)
                if not task_obj:
                    errors.append(f"task_id={task_id_int} が見つかりませんでした。")
                    continue
                task_obj.time = new_time.strip()
                results.append(f"カスタムタスク「{task_obj.name}」の時刻を {task_obj.time} に更新しました。")
                modified_ids.append(f"item_custom_{task_obj.id}")
                dirty = True
                continue

            if action_type == "rename_custom_task":
                task_id = action.get("task_id")
                new_name = action.get("new_name")
                if not new_name:
                    errors.append("rename_custom_task: new_name が指定されていません。")
                    continue
                try:
                    task_id_int = int(task_id)
                except (TypeError, ValueError):
                    errors.append("rename_custom_task: task_id が不正です。")
                    continue
                task_obj = CustomTask.query.get(task_id_int)
                if not task_obj:
                    errors.append(f"task_id={task_id_int} が見つかりませんでした。")
                    continue
                old_name = task_obj.name
                task_obj.name = new_name.strip()
                results.append(f"カスタムタスク「{old_name}」の名前を「{task_obj.name}」に更新しました。")
                modified_ids.append(f"item_custom_{task_obj.id}")
                dirty = True
                continue

            if action_type == "update_custom_task_memo":
                task_id = action.get("task_id")
                new_memo = action.get("new_memo")
                if new_memo is None: # Allow empty memo to clear it
                    errors.append("update_custom_task_memo: new_memo が指定されていません。")
                    continue
                try:
                    task_id_int = int(task_id)
                except (TypeError, ValueError):
                    errors.append("update_custom_task_memo: task_id が不正です。")
                    continue
                task_obj = CustomTask.query.get(task_id_int)
                if not task_obj:
                    errors.append(f"task_id={task_id_int} が見つかりませんでした。")
                    continue
                task_obj.memo = new_memo.strip()
                results.append(f"カスタムタスク「{task_obj.name}」のメモを更新しました。")
                modified_ids.append(f"item_custom_{task_obj.id}")
                dirty = True
                continue

            if action_type == "update_log":
                content = action.get("content")
                if not isinstance(content, str) or not content.strip():
                    errors.append("update_log: content が指定されていません。")
                    continue
                date_value = _parse_date(action.get("date"), default_date)
                day_log = DayLog.query.filter_by(date=date_value).first()
                if not day_log:
                    day_log = DayLog(date=date_value)
                    db.session.add(day_log)
                day_log.content = content.strip()
                results.append(f"{date_value} の日報を更新しました。")
                modified_ids.append("daily-log-card")
                dirty = True
                continue

            if action_type == "append_day_log":
                content = action.get("content")
                if not isinstance(content, str) or not content.strip():
                    errors.append("append_day_log: content が指定されていません。")
                    continue
                date_value = _parse_date(action.get("date"), default_date)
                day_log = DayLog.query.filter_by(date=date_value).first()
                if not day_log:
                    day_log = DayLog(date=date_value)
                    day_log.content = content.strip()
                    db.session.add(day_log)
                else:
                    # Existing log found, append
                    current_content = day_log.content or ""
                    if current_content:
                        day_log.content = current_content + "\n" + content.strip()
                    else:
                        day_log.content = content.strip()
                
                results.append(f"{date_value} の日報に追記しました。")
                modified_ids.append("daily-log-card")
                dirty = True
                continue

            if action_type == "get_day_log":
                date_value = _parse_date(action.get("date"), default_date)
                day_log = DayLog.query.filter_by(date=date_value).first()
                if day_log and day_log.content:
                    results.append(f"{date_value} の日報:\n{day_log.content}")
                else:
                    results.append(f"{date_value} の日報は見つかりませんでした。")
                # This action only reads, so no changes are committed, and no dirty flag needed
                continue
            
            # Routine/Step Management
            if action_type == "add_routine":
                name = action.get("name")
                if not name:
                    errors.append("add_routine: name is required")
                    continue
                days = action.get("days", "0,1,2,3,4")
                desc = action.get("description", "")
                r = Routine(name=name, days=days, description=desc)
                db.session.add(r)
                db.session.flush()
                results.append(f"ルーチン「{name}」(ID: {r.id}) を追加しました。")
                dirty = True
                continue
                
            if action_type == "delete_routine":
                rid = action.get("routine_id")
                r = Routine.query.get(int(rid)) if rid else None
                if r:
                    db.session.delete(r)
                    results.append(f"ルーチン「{r.name}」を削除しました。")
                    dirty = True
                else:
                    errors.append("delete_routine: not found")
                continue

            if action_type == "update_routine_days":
                routine_id = action.get("routine_id")
                new_days = action.get("new_days")
                if not new_days:
                    errors.append("update_routine_days: new_days が指定されていません。")
                    continue
                try:
                    routine_id_int = int(routine_id)
                except (TypeError, ValueError):
                    errors.append("update_routine_days: routine_id が不正です。")
                    continue
                routine_obj = Routine.query.get(routine_id_int)
                if not routine_obj:
                    errors.append(f"routine_id={routine_id_int} が見つかりませんでした。")
                    continue
                routine_obj.days = new_days.strip()
                results.append(f"ルーチン「{routine_obj.name}」の曜日を {routine_obj.days} に更新しました。")
                dirty = True
                continue

            if action_type == "add_step":
                rid = action.get("routine_id")
                name = action.get("name")
                if not rid or not name:
                    errors.append("add_step: routine_id and name required")
                    continue
                s = Step(routine_id=int(rid), name=name, time=action.get("time", "00:00"), category=action.get("category", "Other"))
                db.session.add(s)
                db.session.flush()
                results.append(f"ルーチン(ID:{rid})にステップ「{name}」(ID: {s.id}) を追加しました。")
                modified_ids.append(f"item_routine_{s.id}")
                dirty = True
                continue

            if action_type == "delete_step":
                sid = action.get("step_id")
                s = Step.query.get(int(sid)) if sid else None
                if s:
                    db.session.delete(s)
                    results.append(f"ステップ「{s.name}」を削除しました。")
                    dirty = True
                else:
                    errors.append("delete_step: not found")
                continue

            if action_type == "update_step_time":
                step_id = action.get("step_id")
                new_time = action.get("new_time")
                if not new_time:
                    errors.append("update_step_time: new_time が指定されていません。")
                    continue
                try:
                    step_id_int = int(step_id)
                except (TypeError, ValueError):
                    errors.append("update_step_time: step_id が不正です。")
                    continue
                step_obj = Step.query.get(step_id_int)
                if not step_obj:
                    errors.append(f"step_id={step_id_int} が見つかりませんでした。")
                    continue
                step_obj.time = new_time.strip()
                results.append(f"ステップ「{step_obj.name}」の時刻を {step_obj.time} に更新しました。")
                modified_ids.append(f"item_routine_{step_obj.id}")
                dirty = True
                continue
            
            if action_type == "rename_step":
                step_id = action.get("step_id")
                new_name = action.get("new_name")
                if not new_name:
                    errors.append("rename_step: new_name が指定されていません。")
                    continue
                try:
                    step_id_int = int(step_id)
                except (TypeError, ValueError):
                    errors.append("rename_step: step_id が不正です。")
                    continue
                step_obj = Step.query.get(step_id_int)
                if not step_obj:
                    errors.append(f"step_id={step_id_int} が見つかりませんでした。")
                    continue
                old_name = step_obj.name
                step_obj.name = new_name.strip()
                results.append(f"ステップ「{old_name}」の名前を「{step_obj.name}」に更新しました。")
                modified_ids.append(f"item_routine_{step_obj.id}")
                dirty = True
                continue
            
            if action_type == "update_step_memo":
                step_id = action.get("step_id")
                new_memo = action.get("new_memo")
                if new_memo is None: # Allow empty memo to clear it
                    errors.append("update_step_memo: new_memo が指定されていません。")
                    continue
                try:
                    step_id_int = int(step_id)
                except (TypeError, ValueError):
                    errors.append("update_step_memo: step_id が不正です。")
                    continue
                step_obj = Step.query.get(step_id_int)
                if not step_obj:
                    errors.append(f"step_id={step_id_int} が見つかりませんでした。")
                    continue
                # For now, assuming step_obj has a memo field.
                # If memo is specific to a DailyLog, this logic needs adjustment.
                step_obj.memo = new_memo.strip() 
                results.append(f"ステップ「{step_obj.name}」のメモを更新しました。")
                modified_ids.append(f"item_routine_{step_obj.id}")
                dirty = True
                continue

            if action_type == "list_tasks_in_period":
                start_date = _parse_date(action.get("start_date"), default_date)
                end_date = _parse_date(action.get("end_date"), default_date)

                if start_date > end_date:
                    errors.append("list_tasks_in_period: 開始日が終了日より後です。")
                    continue
                
                tasks_info = []
                
                # Custom Tasks
                custom_tasks = CustomTask.query.filter(CustomTask.date.between(start_date, end_date)).order_by(CustomTask.date, CustomTask.time).all()
                for ct in custom_tasks:
                    tasks_info.append(f"カスタムタスク [{ct.id}]: {ct.date.isoformat()} {ct.time} - {ct.name} (完了: {ct.done}) (メモ: {ct.memo if ct.memo else 'なし'})")

                # Routine Steps (more complex as they are recurring)
                # This would require iterating through each day in the period and checking routines
                current_date = start_date
                while current_date <= end_date:
                    routines_for_day = get_weekday_routines(current_date.weekday())
                    for r in routines_for_day:
                        for s in r.steps:
                            log = DailyLog.query.filter_by(date=current_date, step_id=s.id).first()
                            status = "完了" if log and log.done else "未完了"
                            memo = log.memo if log and log.memo else (s.memo if s.memo else 'なし')
                            tasks_info.append(f"ルーチンステップ [{s.id}]: {current_date.isoformat()} {s.time} - {r.name} - {s.name} (完了: {status}) (メモ: {memo})")
                    current_date += datetime.timedelta(days=1)
                
                if tasks_info:
                    results.append(f"{start_date.isoformat()} から {end_date.isoformat()} までのタスク:\n" + "\n".join(tasks_info))
                else:
                    results.append(f"{start_date.isoformat()} から {end_date.isoformat()} までのタスクは見つかりませんでした。")
                
                # This action only reads, so no changes are committed, and no dirty flag needed
                continue
            
            if action_type == "get_daily_summary":
                target_date = _parse_date(action.get("date"), default_date)
                
                summary_parts = []

                # DayLog content
                day_log = DayLog.query.filter_by(date=target_date).first()
                if day_log and day_log.content:
                    summary_parts.append(f"日報: {day_log.content}")
                else:
                    summary_parts.append("日報: なし")

                # Custom Tasks
                custom_tasks = CustomTask.query.filter_by(date=target_date).all()
                if custom_tasks:
                    summary_parts.append("カスタムタスク:")
                    for ct in custom_tasks:
                        status = "完了" if ct.done else "未完了"
                        summary_parts.append(f"- {ct.time} {ct.name} ({status}) (メモ: {ct.memo if ct.memo else 'なし'})")
                else:
                    summary_parts.append("カスタムタスク: なし")

                # Routine Steps
                routines_for_day = get_weekday_routines(target_date.weekday())
                if routines_for_day:
                    summary_parts.append("ルーチンステップ:")
                    for r in routines_for_day:
                        for s in r.steps:
                            log = DailyLog.query.filter_by(date=target_date, step_id=s.id).first()
                            status = "完了" if log and log.done else "未完了"
                            memo = log.memo if log and log.memo else (s.memo if s.memo else 'なし')
                            summary_parts.append(f"- {s.time} {r.name} - {s.name} ({status}) (メモ: {memo})")
                else:
                    summary_parts.append("ルーチンステップ: なし")
                
                results.append(f"{target_date.isoformat()} の活動概要:\n" + "\n".join(summary_parts))
                continue

            errors.append(f"未知のアクション: {action_type}")
        if dirty:
            db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        errors.append(f"操作の適用に失敗しました: {exc}")
        results = []

    return results, errors, modified_ids

@app.route('/api/calendar')
def api_calendar():
    today = datetime.date.today()
    year = request.args.get('year', today.year, type=int)
    month = request.args.get('month', today.month, type=int)

    if month > 12:
        month = 1
        year += 1
    elif month < 1:
        month = 12
        year -= 1

    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdatescalendar(year, month)

    calendar_data = []
    for week in month_days:
        week_data = []
        for day in week:
            is_current_month = (day.month == month)

            weekday = day.weekday()
            routines = get_weekday_routines(weekday)
            total_steps = sum(len(r.steps) for r in routines)

            logs = DailyLog.query.filter_by(date=day).all()
            completed_count = sum(1 for l in logs if l.done)

            custom_tasks = CustomTask.query.filter_by(date=day).all()
            total_steps += len(custom_tasks)
            completed_count += sum(1 for t in custom_tasks if t.done)

            day_log = DayLog.query.filter_by(date=day).first()
            has_day_log = bool(day_log and day_log.content and day_log.content.strip())

            week_data.append({
                'date': day.isoformat(), # Convert date to ISO string
                'day_num': day.day,
                'is_current_month': is_current_month,
                'total_routines': len(routines) + len(custom_tasks),
                'total_steps': total_steps,
                'completed_steps': completed_count,
                'has_day_log': has_day_log
            })
        calendar_data.append(week_data)

    return jsonify({
        'calendar_data': calendar_data,
        'year': year,
        'month': month,
        'today': today.isoformat()
    })

@app.route('/')
def index():
    today = datetime.date.today()
    year = request.args.get('year', today.year, type=int)
    month = request.args.get('month', today.month, type=int)
    
    if month > 12:
        month = 1
        year += 1
    elif month < 1:
        month = 12
        year -= 1
        
    cal = calendar.Calendar(firstweekday=0) 
    month_days = cal.monthdatescalendar(year, month)
    
    calendar_data = []
    for week in month_days:
        week_data = []
        for day in week:
            is_current_month = (day.month == month)
            
            weekday = day.weekday()
            routines = get_weekday_routines(weekday)
            total_steps = sum(len(r.steps) for r in routines)
            
            logs = DailyLog.query.filter_by(date=day).all()
            completed_count = sum(1 for l in logs if l.done)
            
            custom_tasks = CustomTask.query.filter_by(date=day).all()
            total_steps += len(custom_tasks)
            completed_count += sum(1 for t in custom_tasks if t.done)

            day_log = DayLog.query.filter_by(date=day).first()
            has_day_log = bool(day_log and day_log.content and day_log.content.strip())

            color_class = "bg-light"
            if total_steps > 0:
                ratio = completed_count / total_steps
                if ratio == 1.0:
                    color_class = "bg-success text-white"
                elif ratio > 0.5:
                    color_class = "bg-warning"
                elif ratio > 0:
                    color_class = "bg-info text-white"
            
            week_data.append({
                'date': day,
                'day_num': day.day,
                'is_current_month': is_current_month,
                'total_routines': len(routines) + len(custom_tasks),
                'total_steps': total_steps,
                'completed_steps': completed_count,
                'color_class': color_class,
                'has_day_log': has_day_log
            })
        calendar_data.append(week_data)

    return render_template('index.html', 
                           calendar_data=calendar_data, 
                           year=year, month=month,
                           today=today)

@app.route('/calendar_partial')
def calendar_partial():
    today = datetime.date.today()
    year = request.args.get('year', today.year, type=int)
    month = request.args.get('month', today.month, type=int)
    
    if month > 12:
        month = 1
        year += 1
    elif month < 1:
        month = 12
        year -= 1
        
    cal = calendar.Calendar(firstweekday=0) 
    month_days = cal.monthdatescalendar(year, month)
    
    calendar_data = []
    for week in month_days:
        week_data = []
        for day in week:
            is_current_month = (day.month == month)
            
            weekday = day.weekday()
            routines = get_weekday_routines(weekday)
            total_steps = sum(len(r.steps) for r in routines)
            
            logs = DailyLog.query.filter_by(date=day).all()
            completed_count = sum(1 for l in logs if l.done)
            
            custom_tasks = CustomTask.query.filter_by(date=day).all()
            total_steps += len(custom_tasks)
            completed_count += sum(1 for t in custom_tasks if t.done)

            day_log = DayLog.query.filter_by(date=day).first()
            has_day_log = bool(day_log and day_log.content and day_log.content.strip())
            
            week_data.append({
                'date': day,
                'day_num': day.day,
                'is_current_month': is_current_month,
                'total_routines': len(routines) + len(custom_tasks),
                'total_steps': total_steps,
                'completed_steps': completed_count,
                'has_day_log': has_day_log
            })
        calendar_data.append(week_data)
    
    return render_template('calendar_partial.html', calendar_data=calendar_data, today=today)


@app.route("/embed/calendar")
def embed_calendar():
    today = datetime.date.today()
    year = request.args.get("year", today.year, type=int)
    month = request.args.get("month", today.month, type=int)

    if month > 12:
        month = 1
        year += 1
    elif month < 1:
        month = 12
        year -= 1

    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdatescalendar(year, month)

    calendar_data = []
    for week in month_days:
        week_data = []
        for day in week:
            is_current_month = day.month == month
            weekday = day.weekday()
            routines = get_weekday_routines(weekday)
            total_steps = sum(len(r.steps) for r in routines)

            logs = DailyLog.query.filter_by(date=day).all()
            completed_count = sum(1 for l in logs if l.done)

            custom_tasks = CustomTask.query.filter_by(date=day).all()
            total_steps += len(custom_tasks)
            completed_count += sum(1 for t in custom_tasks if t.done)

            day_log = DayLog.query.filter_by(date=day).first()
            has_day_log = bool(day_log and day_log.content and day_log.content.strip())

            color_class = "bg-light"
            if total_steps > 0:
                ratio = completed_count / total_steps
                if ratio == 1.0:
                    color_class = "bg-success text-white"
                elif ratio > 0.5:
                    color_class = "bg-warning"
                elif ratio > 0:
                    color_class = "bg-info text-white"

            week_data.append(
                {
                    "date": day,
                    "day_num": day.day,
                    "is_current_month": is_current_month,
                    "total_routines": len(routines) + len(custom_tasks),
                    "total_steps": total_steps,
                    "completed_steps": completed_count,
                    "color_class": color_class,
                    "has_day_log": has_day_log,
                }
            )
        calendar_data.append(week_data)

    return render_template(
        "embed_calendar.html",
        calendar_data=calendar_data,
        year=year,
        month=month,
        today=today,
    )


@app.route('/api/day/<date_str>')
def api_day_view(date_str):
    try:
        date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400

    timeline_items, completion_rate = _get_timeline_data(date_obj)
    day_log = DayLog.query.filter_by(date=date_obj).first()

    # Convert complex objects to JSON-serializable dictionaries
    serialized_timeline_items = []
    for item in timeline_items:
        step = item['step']
        # Handle both SQLAlchemy model objects and dicts
        if isinstance(step, dict):
            step_name = step.get('name', '')
            step_category = step.get('category', 'Other')
        else:
            step_name = step.name
            step_category = getattr(step, 'category', 'Other')
        
        routine = item['routine']
        if isinstance(routine, dict):
            routine_name = routine.get('name', '')
        else:
            routine_name = routine.name
        
        log = item['log']
        if isinstance(log, dict):
            log_done = log.get('done', False)
            log_memo = log.get('memo')
        elif log:
            log_done = log.done
            log_memo = log.memo
        else:
            log_done = False
            log_memo = None
        
        is_done = item['real_obj'].done if item.get('real_obj') else log_done
        
        serialized_item = {
            'type': item['type'],
            'time': item['time'],
            'id': item['id'],
            'routine_name': routine_name,
            'step_name': step_name,
            'step_category': step_category,
            'log_done': log_done,
            'log_memo': log_memo,
            'is_done': is_done
        }
        serialized_timeline_items.append(serialized_item)

    return jsonify({
        'date': date_obj.isoformat(),
        'timeline_items': serialized_timeline_items,
        'completion_rate': completion_rate,
        'day_log_content': day_log.content if day_log else None
    })

@app.route('/day/<date_str>', methods=['GET', 'POST'])
def day_view(date_str):
    try:
        date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        if 'add_custom_task' in request.form:
            name = request.form.get('custom_name')
            time = request.form.get('custom_time')
            if name:
                ct = CustomTask(date=date_obj, name=name, time=time)
                db.session.add(ct)
                db.session.commit()
                flash('カスタムタスクを追加しました。')
            return redirect(url_for('day_view', date_str=date_str))

        if 'save_log' in request.form:
            content = request.form.get('day_log_content')
            dlog = DayLog.query.filter_by(date=date_obj).first()
            if not dlog:
                dlog = DayLog(date=date_obj)
                db.session.add(dlog)
            dlog.content = content
            db.session.commit()
            flash('日報を保存しました。')
            return redirect(url_for('day_view', date_str=date_str))

        if 'delete_custom_task' in request.form:
            task_id = request.form.get('delete_custom_task')
            task = CustomTask.query.get(task_id)
            if task:
                db.session.delete(task)
                db.session.commit()
                flash('タスクを削除しました。')
            return redirect(url_for('day_view', date_str=date_str))

        # Update Steps and Custom Tasks
        routines = get_weekday_routines(date_obj.weekday())
        all_steps = []
        for r in routines:
            all_steps.extend(r.steps)
            
        for step in all_steps:
            done_key = f"done_{step.id}"
            memo_key = f"memo_{step.id}"
            is_done = (request.form.get(done_key) == 'on')
            memo_text = request.form.get(memo_key, '')
            
            log = DailyLog.query.filter_by(date=date_obj, step_id=step.id).first()
            if not log:
                log = DailyLog(date=date_obj, step_id=step.id)
                db.session.add(log)
            
            log.done = is_done
            log.memo = memo_text
        
        custom_tasks = CustomTask.query.filter_by(date=date_obj).all()
        for task in custom_tasks:
            done_key = f"custom_done_{task.id}"
            memo_key = f"custom_memo_{task.id}"
            is_done = (request.form.get(done_key) == 'on')
            memo_text = request.form.get(memo_key, '')
            task.done = is_done
            task.memo = memo_text

        db.session.commit()
        flash('進捗を保存しました。')
        return redirect(url_for('day_view', date_str=date_str))

    # GET
    timeline_items, completion_rate = _get_timeline_data(date_obj)
    day_log = DayLog.query.filter_by(date=date_obj).first()
    routines = get_weekday_routines(date_obj.weekday())
    
    return render_template('day.html', date=date_obj, timeline_items=timeline_items, day_log=day_log, completion_rate=completion_rate, routines=routines)

@app.route('/day/<date_str>/timeline')
def day_view_timeline(date_str):
    try:
        date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return "Invalid Date", 400
    
    timeline_items, completion_rate = _get_timeline_data(date_obj)
    # Note: day_log is not used in timeline_partial strictly, but might be if we updated that too. 
    # timeline_partial only uses timeline_items and date/completion_rate.
    
    return render_template('timeline_partial.html', date=date_obj, timeline_items=timeline_items, completion_rate=completion_rate)

@app.route('/day/<date_str>/log_partial')
def day_view_log_partial(date_str):
    try:
        date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return "Invalid Date", 400
    
    day_log = DayLog.query.filter_by(date=date_obj).first()
    return render_template('log_partial.html', day_log=day_log)


@app.route('/api/routines/day/<int:weekday>')
def api_routines_by_day(weekday):
    routines = get_weekday_routines(weekday)
    serialized_routines = []
    for r in routines:
        steps = []
        for s in r.steps:
            steps.append({
                'id': s.id,
                'name': s.name,
                'time': s.time,
                'category': s.category
            })
        steps.sort(key=lambda x: x['time'])
        
        serialized_routines.append({
            'id': r.id,
            'name': r.name,
            'description': r.description,
            'steps': steps
        })
    return jsonify({'routines': serialized_routines})

@app.route('/api/routines')
def api_routines():
    routines = Routine.query.all()
    serialized_routines = []
    for r in routines:
        steps = []
        for s in r.steps:
            steps.append({
                'id': s.id,
                'name': s.name,
                'time': s.time,
                'category': s.category
            })
        serialized_routines.append({
            'id': r.id,
            'name': r.name,
            'days': r.days,
            'description': r.description,
            'steps': steps
        })
    return jsonify({'routines': serialized_routines})

@app.route('/routines')
def routines_list():
    routines = Routine.query.all()
    return render_template('routines.html', routines=routines)

@app.route('/routines/add', methods=['POST'])
def add_routine():
    name = request.form.get('name')
    days = ",".join(request.form.getlist('days'))
    desc = request.form.get('description')
    if name:
        r = Routine(name=name, days=days, description=desc)
        db.session.add(r)
        db.session.commit()
    return redirect(url_for('routines_list'))

@app.route('/routines/<int:id>/delete', methods=['POST'])
def delete_routine(id):
    r = Routine.query.get_or_404(id)
    db.session.delete(r)
    db.session.commit()
    return redirect(url_for('routines_list'))

@app.route('/routines/<int:id>/step/add', methods=['POST'])
def add_step(id):
    r = Routine.query.get_or_404(id)
    name = request.form.get('name')
    time = request.form.get('time')
    category = request.form.get('category')
    if name:
        s = Step(routine_id=r.id, name=name, time=time, category=category)
        db.session.add(s)
        db.session.commit()
    return redirect(url_for('routines_list'))

@app.route('/steps/<int:id>/delete', methods=['POST'])
def delete_step(id):
    s = Step.query.get_or_404(id)
    db.session.delete(s)
    db.session.commit()
    return redirect(url_for('routines_list'))

@app.get("/api/models")
def list_models():
    provider, model, base_url, _ = apply_model_selection("scheduler")
    return jsonify(
        {
            "models": current_available_models(),
            "current": {"provider": provider, "model": model, "base_url": base_url},
        }
    )

@app.post("/model_settings")
def update_model_settings():
    payload = request.get_json(silent=True) or {}
    selection = payload.get("selection") if "selection" in payload else payload
    if isinstance(selection, dict) and "scheduler" in selection:
        selection = selection.get("scheduler")
    if selection is not None and not isinstance(selection, dict):
        return jsonify({"error": "selection must be an object"}), 400

    try:
        provider, model, base_url, _ = update_override(selection if selection else None)
    except Exception as exc:
        return jsonify({"error": f"モデル設定の更新に失敗しました: {exc}"}), 500
    return jsonify({"status": "ok", "applied": {"provider": provider, "model": model, "base_url": base_url}})

@app.route("/api/chat/history", methods=["GET", "DELETE"])
def manage_chat_history():
    if request.method == "DELETE":
        try:
            ChatHistory.query.delete()
            db.session.commit()
            return jsonify({"status": "cleared"})
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500
    
    # GET
    history = ChatHistory.query.order_by(ChatHistory.timestamp).all()
    return jsonify({
        "history": [
            {"role": h.role, "content": h.content, "timestamp": h.timestamp.isoformat()}
            for h in history
        ]
    })


@app.post("/api/conversations/review")
def review_conversation_history():
    payload = request.get_json(silent=True) or {}
    raw_history = payload.get("history")
    if raw_history is None:
        raw_history = payload.get("messages")

    history_messages = _normalise_history_messages(raw_history)
    if not history_messages:
        return jsonify({"error": "history must be a non-empty array"}), 400

    today = datetime.date.today()
    context = _build_scheduler_context(today)

    try:
        review = _call_conversation_review(history_messages, context)
    except Exception as exc:
        return jsonify({"error": f"会話履歴の分析に失敗しました: {exc}"}), 500

    actions = review.get("actions") if isinstance(review.get("actions"), list) else []
    results, errors, modified_ids = _apply_actions(actions, today)
    action_taken = bool(results)

    base_reply = review.get("reply") if isinstance(review.get("reply"), str) else ""

    if results or errors:
        summary_client = UnifiedClient()
        result_text = ""
        if results:
            result_text += "【実行結果】\n" + "\n".join(f"- {item}" for item in results) + "\n"
        if errors:
            result_text += "【エラー】\n" + "\n".join(f"- {err}" for err in errors) + "\n"

        summary_system_prompt = (
            "あなたはユーザーのスケジュール管理をサポートする親しみやすいAIパートナーです。\n"
            "会話の流れとシステムのアクション実行結果をもとに、ユーザーへの最終的な回答を作成してください。\n"
            "\n"
            "## ガイドライン\n"
            "1. **フレンドリーに**: 絵文字（📅, ✅, ✨など）を使用し、丁寧語（です・ます）で話してください。\n"
            "2. **分かりやすく**: 実行結果を自然な文章に統合してください。\n"
            "3. **エラーへの対応**: エラーは優しく伝えてください。\n"
        )
        
        last_user_msg = "（会話履歴からの自動対応）"
        if history_messages and history_messages[-1]['role'] == 'user':
             last_user_msg = history_messages[-1]['content']

        summary_messages = [
            {"role": "system", "content": summary_system_prompt},
            {"role": "user", "content": f"直近のユーザー発言: {last_user_msg}\n\n{result_text}\n\n元のアシスタントの応答案: {base_reply}"}
        ]

        try:
            resp = summary_client.create(
                messages=summary_messages,
                temperature=0.7,
                max_tokens=1000
            )
            final_reply = _content_to_text(resp.choices[0].message.content)
        except Exception as e:
            # Fallback
            reply_parts = []
            if base_reply: reply_parts.append(base_reply)
            if results: reply_parts.append("実行結果:\n" + "\n".join(f"- {item}" for item in results))
            if errors: reply_parts.append("エラー:\n" + "\n".join(f"- {err}" for err in errors))
            final_reply = "\n\n".join(reply_parts)
    else:
        final_reply = base_reply

    return jsonify(
        {
            "action_required": bool(review.get("action_required") or actions),
            "action_taken": action_taken,
            "actions": actions,
            "results": [], # Multi-Agent-Platform での自動表示を抑制
            "_original_results": results,
            "errors": errors,
            "modified_ids": modified_ids,
            "should_reply": bool(review.get("should_reply") or final_reply),
            "reply": final_reply,
            "notes": review.get("notes") if isinstance(review.get("notes"), str) else "",
        }
    )

def process_chat_request(message_or_history: Union[str, List[Dict[str, str]]], save_history: bool = True) -> Dict[str, Any]:
    """Process a natural language request using the scheduler agent's logic."""
    
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

    # Save user message (optional in this context, but good for consistency if we want to track it)
    # For MCP usage, we might skip saving to ChatHistory table or save it with a special flag?
    # Let's save it for now as it's valuable debugging info.
    if save_history:
        try:
            db.session.add(ChatHistory(role="user", content=user_message))
            db.session.commit()
        except Exception as e:
            print(f"Failed to save user message: {e}")

    today = datetime.date.today()
    context = _build_scheduler_context(today)

    try:
        reply_text, actions = call_scheduler_llm(formatted_messages, context)
    except Exception as exc:
        return {
            "reply": f"LLM 呼び出しに失敗しました: {exc}",
            "should_refresh": False,
            "modified_ids": []
        }

    results, errors, modified_ids = _apply_actions(actions, today)

    # If actions were executed, use the LLM to generate a friendly report of the results.
    if results or errors:
        summary_client = UnifiedClient()
        
        # Context for the summarization
        result_text = ""
        if results:
            result_text += "【実行結果】\n" + "\n".join(f"- {item}" for item in results) + "\n"
        if errors:
            result_text += "【エラー】\n" + "\n".join(f"- {err}" for err in errors) + "\n"
            
        summary_system_prompt = (
            "あなたはユーザーのスケジュール管理をサポートする親しみやすいAIパートナーです。\n"
            "ユーザーの要望に対してシステムがアクションを実行しました。\n"
            "その「実行結果」をもとに、ユーザーへの最終的な回答を作成してください。\n"
            "\n"
            "## ガイドライン\n"
            "1. **フレンドリーに**: 絵文字（📅, ✅, ✨, 👍など）を適度に使用し、硬苦しくない丁寧語（です・ます）で話してください。\n"
            "2. **分かりやすく**: 実行結果の羅列（「カスタムタスク[2]...」のような形式）は避け、人間が読みやすい文章に整形してください。\n"
            "   - 例: 「12月10日の9時から『カラオケ』の予定が入っていますね！楽しんできてください🎤」\n"
            "3. **エラーへの対応**: エラーがある場合は、優しくその旨を伝え、どうすればよいか（もし分かれば）示唆してください。\n"
            "4. **元の文脈を維持**: ユーザーの元の発言に対する返答として自然になるようにしてください。\n"
        )
        
        summary_messages = [
            {"role": "system", "content": summary_system_prompt},
            {"role": "user", "content": f"ユーザーの発言: {user_message}\n\n{result_text}"}
        ]

        try:
            resp = summary_client.create(
                messages=summary_messages,
                temperature=0.7,
                max_tokens=1000
            )
            final_reply = _content_to_text(resp.choices[0].message.content)
            
        except Exception as e:
            # Fallback
            final_reply = (reply_text or "") + "\n\n" + result_text
            print(f"Summary LLM failed: {e}")

    else:
        # No actions, just use the original reply
        final_reply = reply_text if reply_text else "了解しました。"

    # Save assistant reply
    if save_history:
        try:
            db.session.add(ChatHistory(role="assistant", content=final_reply))
            db.session.commit()
        except Exception as e:
            print(f"Failed to save assistant message: {e}")

    return {
        "reply": final_reply,
        "should_refresh": (len(results) > 0),
        "modified_ids": modified_ids
    }

@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        return jsonify({"error": "messages must be a list"}), 400

    formatted_messages = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str):
            continue
        formatted_messages.append({"role": role, "content": content})

    if not formatted_messages or formatted_messages[-1]["role"] != "user":
        return jsonify({"error": "last message must be from user"}), 400

    # Pass the last 10 messages to include context
    recent_messages = formatted_messages[-10:]
    
    result = process_chat_request(recent_messages)
    
    return jsonify(result)

# --- Evaluation Routes ---

@app.route('/evaluation')
def evaluation_page():
    return render_template('evaluation.html')

@app.post("/api/evaluation/chat")
def evaluation_chat():
    payload = request.get_json(silent=True) or {}
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        return jsonify({"error": "messages must be a list"}), 400

    formatted_messages = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str):
            continue
        formatted_messages.append({"role": role, "content": content})

    if not formatted_messages or formatted_messages[-1]["role"] != "user":
        return jsonify({"error": "last message must be from user"}), 400

    # Custom logic for evaluation to return full details
    today = datetime.date.today()
    context = _build_scheduler_context(today)

    try:
        reply_text, actions = call_scheduler_llm(formatted_messages, context)
    except Exception as exc:
        return jsonify({"error": f"LLM Error: {exc}"}), 500

    results, errors, modified_ids = _apply_actions(actions, today)
    
    # Generate summary if needed, similar to main chat
    final_reply = reply_text
    if results or errors:
        summary_client = UnifiedClient()
        result_text = ""
        if results:
            result_text += "【実行結果】\n" + "\n".join(f"- {item}" for item in results) + "\n"
        if errors:
            result_text += "【エラー】\n" + "\n".join(f"- {err}" for err in errors) + "\n"
            
        summary_system_prompt = (
            "あなたはユーザーのスケジュール管理をサポートする親しみやすいAIパートナーです。\n"
            "ユーザーの要望に対してシステムがアクションを実行しました。\n"
            "その「実行結果」をもとに、ユーザーへの最終的な回答を作成してください。\n"
            "\n"
            "## ガイドライン\n"
            "1. **フレンドリーに**: 絵文字（📅, ✅, ✨, 👍など）を適度に使用し、硬苦しくない丁寧語（です・ます）で話してください。\n"
            "2. **分かりやすく**: 実行結果の羅列は避け、人間が読みやすい文章に整形してください。\n"
            "3. **エラーへの対応**: エラーがある場合は、優しくその旨を伝え、どうすればよいか（もし分かれば）示唆してください。\n"
        )
        user_message = formatted_messages[-1]["content"]
        summary_messages = [
            {"role": "system", "content": summary_system_prompt},
            {"role": "user", "content": f"ユーザーの発言: {user_message}\n\n{result_text}"}
        ]
        try:
            resp = summary_client.create(
                messages=summary_messages,
                temperature=0.7,
                max_tokens=1000
            )
            final_reply = _content_to_text(resp.choices[0].message.content)
        except Exception:
            final_reply = (reply_text or "") + "\n\n" + result_text

    return jsonify({
        "reply": final_reply,
        "raw_reply": reply_text,
        "actions": actions,
        "results": results,
        "errors": errors
    })

@app.post("/api/evaluation/reset")
def evaluation_reset():
    try:
        db.session.query(DailyLog).delete()
        db.session.query(CustomTask).delete()
        db.session.query(Step).delete()
        db.session.query(Routine).delete()
        db.session.query(DayLog).delete()
        # db.session.query(EvaluationResult).delete() # Keep history? User said "delete all recorded data".
        # Assuming this refers to the Scheduler data to reset the test environment.
        db.session.commit()
        return jsonify({"status": "ok", "message": "Scheduler data cleared."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.post("/api/evaluation/seed")
def evaluation_seed():
    try:
        date_str = request.json.get("date")
        if date_str:
            target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            target_date = datetime.date.today()
        
        messages = _seed_evaluation_data(target_date, target_date)
        return jsonify({"status": "ok", "message": "; ".join(messages)})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.post("/api/evaluation/seed_period")
def evaluation_seed_period():
    try:
        start_date_str = request.json.get("start_date")
        end_date_str = request.json.get("end_date")

        if not start_date_str or not end_date_str:
            return jsonify({"error": "start_date and end_date are required"}), 400

        start_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()

        if start_date > end_date:
            return jsonify({"error": "start_date cannot be after end_date"}), 400
        
        messages = _seed_evaluation_data(start_date, end_date)
        return jsonify({"status": "ok", "message": "; ".join(messages)})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


def _seed_evaluation_data(start_date: datetime.date, end_date: datetime.date):
    messages = []
    
    # Ensure Daily Routine exists
    routine_name = "Daily Routine"
    daily_routine = Routine.query.filter_by(name=routine_name).first()
    if not daily_routine:
        daily_routine = Routine(name=routine_name, days="0,1,2,3,4,5,6", description="General daily habits")
        db.session.add(daily_routine)
        db.session.flush() # get ID
        
        steps_data = [
            ("07:00", "Wake up", "Lifestyle"),
            ("08:00", "Breakfast", "Lifestyle"),
            ("09:00", "Check Emails", "Browser"),
            ("12:00", "Lunch", "Lifestyle"),
            ("18:00", "Workout", "Lifestyle"),
            ("22:00", "Read Book", "Lifestyle")
        ]
        for time, name, category in steps_data:
            s = Step(routine_id=daily_routine.id, name=name, time=time, category=category)
            db.session.add(s)
        messages.append(f"Seeded Routine '{routine_name}'")

    current_date = start_date
    while current_date <= end_date:
        # Clear existing data for the current date
        DailyLog.query.filter_by(date=current_date).delete()
        CustomTask.query.filter_by(date=current_date).delete()
        DayLog.query.filter_by(date=current_date).delete()
        messages.append(f"Cleared existing data for {current_date.isoformat()}")

        # Seed DayLog
        log_content = f"これは{current_date.isoformat()}の評価用日報です。今日の気分は最高です！"
        db.session.add(DayLog(date=current_date, content=log_content))
        messages.append(f"Seeded DayLog for {current_date.isoformat()}")

        # Seed Custom Tasks
        db.session.add(CustomTask(date=current_date, name=f"ミーティング ({current_date.day}日)", time="10:00", memo="重要な議題"))
        db.session.add(CustomTask(date=current_date, name=f"レポート作成 ({current_date.day}日)", time="14:00", memo="期限は明日"))
        messages.append(f"Seeded Custom Tasks for {current_date.isoformat()}")
        
        # Mark some routine steps as done randomly to simulate progress
        if daily_routine:
            all_steps = Step.query.filter_by(routine_id=daily_routine.id).all()
            if all_steps:
                if len(all_steps) >= 1:
                    log_entry = DailyLog(date=current_date, step_id=all_steps[0].id, done=True, memo="朝の活動完了")
                    db.session.add(log_entry)
                    messages.append(f"Marked step '{all_steps[0].name}' as done for {current_date.isoformat()}")
                if len(all_steps) >= 3:
                    log_entry = DailyLog(date=current_date, step_id=all_steps[2].id, done=True, memo="メールチェック完了")
                    db.session.add(log_entry)
                    messages.append(f"Marked step '{all_steps[2].name}' as done for {current_date.isoformat()}")

        current_date += datetime.timedelta(days=1)
    
    db.session.commit()
    return messages

@app.post("/api/add_sample_data")
def add_sample_data():
    try:
        today = datetime.date.today()
        messages = []

        # 1. DayLog for last Friday (Existing logic)
        # 0=Mon, 4=Fri.
        days_behind = (today.weekday() - 4) % 7
        if days_behind <= 0:
             days_behind += 7
        last_friday = today - datetime.timedelta(days=days_behind)
        
        log = DayLog.query.filter_by(date=last_friday).first()
        if not log:
            log = DayLog(date=last_friday, content="先週の金曜日はとても良い天気でした。プロジェクトの進捗も順調でした。")
            db.session.add(log)
            messages.append(f"Seeded DayLog for {last_friday}")
        
        # 2. Daily Routine
        routine_name = "Daily Routine"
        daily_routine = Routine.query.filter_by(name=routine_name).first()
        if not daily_routine:
            daily_routine = Routine(name=routine_name, days="0,1,2,3,4,5,6", description="General daily habits")
            db.session.add(daily_routine)
            db.session.flush() # get ID
            
            steps_data = [
                ("07:00", "Wake up", "Lifestyle"),
                ("08:00", "Breakfast", "Lifestyle"),
                ("09:00", "Check Emails", "Browser")
            ]
            for time, name, category in steps_data:
                s = Step(routine_id=daily_routine.id, name=name, time=time, category=category)
                db.session.add(s)
            messages.append(f"Seeded Routine '{routine_name}'")
        
        # 3. Custom Tasks
        
        # Task for Today
        task_name = "Buy Milk"
        if not CustomTask.query.filter_by(date=today, name=task_name).first():
            db.session.add(CustomTask(date=today, name=task_name, time="18:00", memo="Low fat"))
            messages.append(f"Seeded Task '{task_name}' for Today ({today})")

        # Task for Tomorrow
        tomorrow = today + datetime.timedelta(days=1)
        tasks_tomorrow = [
            ("13:00", "Lunch with Alice", "At the Italian place"),
            ("15:00", "Doctor Appointment", "Bring ID")
        ]
        for time, name, memo in tasks_tomorrow:
            if not CustomTask.query.filter_by(date=tomorrow, name=name).first():
                db.session.add(CustomTask(date=tomorrow, name=name, time=time, memo=memo))
                messages.append(f"Seeded Task '{name}' for Tomorrow ({tomorrow})")

        # Task for Day after Tomorrow
        day_after = today + datetime.timedelta(days=2)
        task_name_da = "Gym"
        if not CustomTask.query.filter_by(date=day_after, name=task_name_da).first():
            db.session.add(CustomTask(date=day_after, name=task_name_da, time="19:00", memo="Leg day"))
            messages.append(f"Seeded Task '{task_name_da}' for Day after Tomorrow ({day_after})")

        db.session.commit()
        
        if not messages:
            return jsonify({"status": "ok", "message": "Data already exists, nothing new seeded."})
            
        return jsonify({"status": "ok", "message": "; ".join(messages)})
            
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@app.post("/api/evaluation/log")
def evaluation_log():
    data = request.get_json(silent=True) or {}
    try:
        res = EvaluationResult(
            model_name=data.get("model_name"),
            task_prompt=data.get("task_prompt"),
            agent_reply=data.get("agent_reply"),
            tool_calls=json.dumps(data.get("tool_calls", [])),
            is_success=data.get("is_success"),
            comments=data.get("comments")
        )
        db.session.add(res)
        db.session.commit()
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.get("/api/evaluation/history")
def evaluation_history():
    results = EvaluationResult.query.order_by(EvaluationResult.timestamp.desc()).all()
    data = []
    for r in results:
        data.append({
            "id": r.id,
            "timestamp": r.timestamp.isoformat(),
            "model_name": r.model_name,
            "task_prompt": r.task_prompt,
            "is_success": r.is_success
        })
    return jsonify({"history": data})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5010, debug=True)
