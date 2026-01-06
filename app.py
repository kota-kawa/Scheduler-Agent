import calendar
import datetime
import json
import os
import threading
from urllib.parse import urlencode
from typing import Any, Dict, Iterator, List, Union

from dateutil import parser as date_parser
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Column, Text, delete
from sqlmodel import Field, Relationship, SQLModel, Session, create_engine, select
try:
    from starlette.middleware.proxy_headers import ProxyHeadersMiddleware
except ModuleNotFoundError:  # pragma: no cover - fallback for older/newer Starlette
    class ProxyHeadersMiddleware:  # type: ignore[no-redef]
        def __init__(self, app, trusted_hosts="*"):
            self.app = app

        async def __call__(self, scope, receive, send):
            await self.app(scope, receive, send)

from starlette.middleware.sessions import SessionMiddleware

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

load_dotenv("secrets.env")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://scheduler:scheduler@localhost:5432/scheduler",
)


def _build_engine(database_url: str):
    normalized_url = database_url
    if normalized_url.startswith("postgres://"):
        normalized_url = normalized_url.replace("postgres://", "postgresql+psycopg2://", 1)

    connect_args: Dict[str, Any] = {}
    if normalized_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    if connect_args:
        return create_engine(normalized_url, connect_args=connect_args)
    return create_engine(normalized_url)


engine = _build_engine(DATABASE_URL)
_db_initialized = False
_db_init_lock = threading.Lock()


class Routine(SQLModel, table=True):
    __tablename__ = "routine"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    days: str = Field(default="0,1,2,3,4", max_length=50)
    description: str | None = Field(default=None, max_length=200)
    steps: list["Step"] = Relationship(
        back_populates="routine", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class Step(SQLModel, table=True):
    __tablename__ = "step"

    id: int | None = Field(default=None, primary_key=True)
    routine_id: int = Field(foreign_key="routine.id")
    name: str = Field(max_length=100)
    time: str = Field(default="00:00", max_length=10)
    category: str = Field(default="Other", max_length=50)
    memo: str | None = Field(default=None, max_length=200)

    routine: Routine | None = Relationship(back_populates="steps")


class DailyLog(SQLModel, table=True):
    __tablename__ = "daily_log"

    id: int | None = Field(default=None, primary_key=True)
    date: datetime.date
    step_id: int = Field(foreign_key="step.id")
    done: bool = Field(default=False)
    memo: str | None = Field(default=None, max_length=200)

    step: Step | None = Relationship()


class CustomTask(SQLModel, table=True):
    __tablename__ = "custom_task"

    id: int | None = Field(default=None, primary_key=True)
    date: datetime.date
    name: str = Field(max_length=100)
    time: str = Field(default="00:00", max_length=10)
    done: bool = Field(default=False)
    memo: str | None = Field(default=None, max_length=200)


class DayLog(SQLModel, table=True):
    __tablename__ = "day_log"

    id: int | None = Field(default=None, primary_key=True)
    date: datetime.date
    content: str | None = Field(default=None, sa_column=Column(Text))


class ChatHistory(SQLModel, table=True):
    __tablename__ = "chat_history"

    id: int | None = Field(default=None, primary_key=True)
    role: str = Field(max_length=20)
    content: str = Field(sa_column=Column(Text, nullable=False))
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.now)


class EvaluationResult(SQLModel, table=True):
    __tablename__ = "evaluation_result"

    id: int | None = Field(default=None, primary_key=True)
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.now)
    model_name: str | None = Field(default=None, max_length=100)
    task_prompt: str | None = Field(default=None, sa_column=Column(Text))
    agent_reply: str | None = Field(default=None, sa_column=Column(Text))
    tool_calls: str | None = Field(default=None, sa_column=Column(Text))
    is_success: bool | None = Field(default=None)
    comments: str | None = Field(default=None, sa_column=Column(Text))


app = FastAPI(root_path=os.getenv("PROXY_PREFIX", ""))
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "devkey"))

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


def _ensure_db_initialized() -> None:
    global _db_initialized
    if _db_initialized:
        return
    with _db_init_lock:
        if _db_initialized:
            return
        SQLModel.metadata.create_all(bind=engine)
        _db_initialized = True


@app.on_event("startup")
def _init_db() -> None:
    _ensure_db_initialized()


def create_session() -> Session:
    _ensure_db_initialized()
    return Session(engine)


def get_db() -> Iterator[Session]:
    _ensure_db_initialized()
    with Session(engine) as db:
        yield db


def flash(request: Request, message: str) -> None:
    flashes = request.session.setdefault("_flashes", [])
    flashes.append(message)
    request.session["_flashes"] = flashes


def pop_flashed_messages(request: Request) -> List[str]:
    return request.session.pop("_flashes", [])


def template_response(request: Request, template_name: str, context: Dict[str, Any]) -> HTMLResponse:
    payload = dict(context)
    payload.setdefault("request", request)
    payload.setdefault("proxy_prefix", request.scope.get("root_path", ""))

    def _url_for(endpoint: str, **values: Any) -> str:
        param_names: set[str] = set()
        for route in request.app.router.routes:
            if getattr(route, "name", None) == endpoint:
                param_names = set(getattr(route, "param_convertors", {}).keys())
                break
        if values and not param_names:
            try:
                return str(request.url_for(endpoint, **values))
            except Exception:
                pass
        path_params = {k: v for k, v in values.items() if k in param_names}
        query_params = {k: v for k, v in values.items() if k not in param_names}
        url = request.url_for(endpoint, **path_params)
        if query_params:
            url = f"{url}?{urlencode(query_params)}"
        return str(url)

    payload.setdefault("url_for", _url_for)
    payload.setdefault("get_flashed_messages", lambda: pop_flashed_messages(request))
    return templates.TemplateResponse(template_name, payload)


# Helpers

def get_weekday_routines(db: Session, weekday_int: int) -> List[Routine]:
    all_routines = db.exec(select(Routine)).all()
    matched = []
    for r in all_routines:
        if str(weekday_int) in (r.days or "").split(","):
            matched.append(r)
    return matched


def _parse_date(value: Any, default_date: datetime.date) -> datetime.date:
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


def _bool_from_value(value: Any, default: bool = False) -> bool:
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


def _get_timeline_data(db: Session, date_obj: datetime.date):
    routines = get_weekday_routines(db, date_obj.weekday())
    custom_tasks = db.exec(select(CustomTask).where(CustomTask.date == date_obj)).all()

    timeline_items = []
    total_items = 0
    completed_items = 0

    for r in routines:
        for s in r.steps:
            log = db.exec(
                select(DailyLog).where(DailyLog.date == date_obj, DailyLog.step_id == s.id)
            ).first()
            timeline_items.append(
                {
                    "type": "routine",
                    "routine": r,
                    "step": s,
                    "log": log,
                    "time": s.time,
                    "id": s.id,
                }
            )
            total_items += 1
            if log and log.done:
                completed_items += 1

    for ct in custom_tasks:
        timeline_items.append(
            {
                "type": "custom",
                "routine": {"name": "Personal"},
                "step": {"name": ct.name, "category": "Custom", "id": ct.id},
                "log": {"done": ct.done, "memo": ct.memo},
                "time": ct.time,
                "id": ct.id,
                "real_obj": ct,
            }
        )
        total_items += 1
        if ct.done:
            completed_items += 1

    timeline_items.sort(key=lambda x: x["time"])

    completion_rate = 0
    if total_items > 0:
        completion_rate = int((completed_items / total_items) * 100)

    return timeline_items, completion_rate


def _build_scheduler_context(db: Session, today: datetime.date | None = None) -> str:
    today = today or datetime.date.today()
    routines = db.exec(select(Routine)).all()
    today_logs = {
        log.step_id: log for log in db.exec(select(DailyLog).where(DailyLog.date == today)).all()
    }
    custom_tasks = db.exec(select(CustomTask).where(CustomTask.date == today)).all()

    recent_day_logs = []
    for i in range(3):
        d = today - datetime.timedelta(days=i)
        dl = db.exec(select(DayLog).where(DayLog.date == d)).first()
        if dl and dl.content:
            recent_day_logs.append(f"Date: {d.isoformat()} | Content: {dl.content}")

    routine_lines = []
    for r in routines:
        days_label = r.days or ""
        steps = (
            ", ".join(
                f"[{s.id}] {s.time} {s.name} ({s.category})"
                for s in sorted(r.steps, key=lambda item: item.time)
            )
            or "no steps"
        )
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
    lines = []
    for entry in history_messages:
        role = entry.get("role")
        content = entry.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            continue
        lines.append(f"{role}: {content.strip()}")
    return "\n".join(lines) or "会話ログは空でした。"


def _normalise_history_messages(raw_history: Any) -> List[Dict[str, str]]:
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
        "- 「今週のタスクを確認して」→ 発言する\n\n"
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
        reply_text, actions, decision = _extract_actions_from_claude_blocks(
            getattr(response, "content", None)
        )
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
        actions, decision = (
            _extract_actions_from_tool_calls(getattr(message, "tool_calls", []))
            if message
            else ([], None)
        )
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


def _apply_actions(db: Session, actions: List[Dict[str, Any]], default_date: datetime.date):
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
                new_task = CustomTask(
                    date=date_value, name=name.strip(), time=time_value.strip(), memo=memo.strip()
                )
                db.add(new_task)
                db.flush()
                results.append(
                    f"カスタムタスク「{new_task.name}」(ID: {new_task.id}) を {date_value} の {new_task.time} に追加しました。"
                )
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
                task_obj = db.get(CustomTask, task_id_int)
                if not task_obj:
                    errors.append(f"task_id={task_id_int} が見つかりませんでした。")
                    continue
                db.delete(task_obj)
                results.append(f"カスタムタスク「{task_obj.name}」を削除しました。")
                dirty = True
                continue

            if action_type == "toggle_step":
                step_id = action.get("step_id")
                try:
                    step_id_int = int(step_id)
                except (TypeError, ValueError):
                    errors.append("toggle_step: step_id が不正です。")
                    continue
                step_obj = db.get(Step, step_id_int)
                if not step_obj:
                    errors.append(f"step_id={step_id_int} が見つかりませんでした。")
                    continue
                date_value = _parse_date(action.get("date"), default_date)
                log = db.exec(
                    select(DailyLog).where(
                        DailyLog.date == date_value, DailyLog.step_id == step_obj.id
                    )
                ).first()
                if not log:
                    log = DailyLog(date=date_value, step_id=step_obj.id)
                    db.add(log)
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
                task_obj = db.get(CustomTask, task_id_int)
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
                task_obj = db.get(CustomTask, task_id_int)
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
                task_obj = db.get(CustomTask, task_id_int)
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
                if new_memo is None:
                    errors.append("update_custom_task_memo: new_memo が指定されていません。")
                    continue
                try:
                    task_id_int = int(task_id)
                except (TypeError, ValueError):
                    errors.append("update_custom_task_memo: task_id が不正です。")
                    continue
                task_obj = db.get(CustomTask, task_id_int)
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
                day_log = db.exec(select(DayLog).where(DayLog.date == date_value)).first()
                if not day_log:
                    day_log = DayLog(date=date_value)
                    db.add(day_log)
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
                day_log = db.exec(select(DayLog).where(DayLog.date == date_value)).first()
                if not day_log:
                    day_log = DayLog(date=date_value)
                    day_log.content = content.strip()
                    db.add(day_log)
                else:
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
                day_log = db.exec(select(DayLog).where(DayLog.date == date_value)).first()
                if day_log and day_log.content:
                    results.append(f"{date_value} の日報:\n{day_log.content}")
                else:
                    results.append(f"{date_value} の日報は見つかりませんでした。")
                continue

            if action_type == "add_routine":
                name = action.get("name")
                if not name:
                    errors.append("add_routine: name is required")
                    continue
                days = action.get("days", "0,1,2,3,4")
                desc = action.get("description", "")
                r = Routine(name=name, days=days, description=desc)
                db.add(r)
                db.flush()
                results.append(f"ルーチン「{name}」(ID: {r.id}) を追加しました。")
                dirty = True
                continue

            if action_type == "delete_routine":
                rid = action.get("routine_id")
                r = db.get(Routine, int(rid)) if rid else None
                if r:
                    db.delete(r)
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
                routine_obj = db.get(Routine, routine_id_int)
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
                s = Step(
                    routine_id=int(rid),
                    name=name,
                    time=action.get("time", "00:00"),
                    category=action.get("category", "Other"),
                )
                db.add(s)
                db.flush()
                results.append(f"ルーチン(ID:{rid})にステップ「{name}」(ID: {s.id}) を追加しました。")
                modified_ids.append(f"item_routine_{s.id}")
                dirty = True
                continue

            if action_type == "delete_step":
                sid = action.get("step_id")
                s = db.get(Step, int(sid)) if sid else None
                if s:
                    db.delete(s)
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
                step_obj = db.get(Step, step_id_int)
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
                step_obj = db.get(Step, step_id_int)
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
                if new_memo is None:
                    errors.append("update_step_memo: new_memo が指定されていません。")
                    continue
                try:
                    step_id_int = int(step_id)
                except (TypeError, ValueError):
                    errors.append("update_step_memo: step_id が不正です。")
                    continue
                step_obj = db.get(Step, step_id_int)
                if not step_obj:
                    errors.append(f"step_id={step_id_int} が見つかりませんでした。")
                    continue
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

                custom_tasks = db.exec(
                    select(CustomTask)
                    .where(CustomTask.date.between(start_date, end_date))
                    .order_by(CustomTask.date, CustomTask.time)
                ).all()
                for ct in custom_tasks:
                    tasks_info.append(
                        f"カスタムタスク [{ct.id}]: {ct.date.isoformat()} {ct.time} - {ct.name} (完了: {ct.done}) (メモ: {ct.memo if ct.memo else 'なし'})"
                    )

                current_date = start_date
                while current_date <= end_date:
                    routines_for_day = get_weekday_routines(db, current_date.weekday())
                    for r in routines_for_day:
                        for s in r.steps:
                            log = db.exec(
                                select(DailyLog).where(
                                    DailyLog.date == current_date, DailyLog.step_id == s.id
                                )
                            ).first()
                            status = "完了" if log and log.done else "未完了"
                            memo = log.memo if log and log.memo else (s.memo if s.memo else "なし")
                            tasks_info.append(
                                f"ルーチンステップ [{s.id}]: {current_date.isoformat()} {s.time} - {r.name} - {s.name} (完了: {status}) (メモ: {memo})"
                            )
                    current_date += datetime.timedelta(days=1)

                if tasks_info:
                    results.append(
                        f"{start_date.isoformat()} から {end_date.isoformat()} までのタスク:\n"
                        + "\n".join(tasks_info)
                    )
                else:
                    results.append(
                        f"{start_date.isoformat()} から {end_date.isoformat()} までのタスクは見つかりませんでした。"
                    )
                continue

            if action_type == "get_daily_summary":
                target_date = _parse_date(action.get("date"), default_date)

                summary_parts = []

                day_log = db.exec(select(DayLog).where(DayLog.date == target_date)).first()
                if day_log and day_log.content:
                    summary_parts.append(f"日報: {day_log.content}")
                else:
                    summary_parts.append("日報: なし")

                custom_tasks = db.exec(
                    select(CustomTask).where(CustomTask.date == target_date)
                ).all()
                if custom_tasks:
                    summary_parts.append("カスタムタスク:")
                    for ct in custom_tasks:
                        status = "完了" if ct.done else "未完了"
                        summary_parts.append(
                            f"- {ct.time} {ct.name} ({status}) (メモ: {ct.memo if ct.memo else 'なし'})"
                        )
                else:
                    summary_parts.append("カスタムタスク: なし")

                routines_for_day = get_weekday_routines(db, target_date.weekday())
                if routines_for_day:
                    summary_parts.append("ルーチンステップ:")
                    for r in routines_for_day:
                        for s in r.steps:
                            log = db.exec(
                                select(DailyLog).where(
                                    DailyLog.date == target_date, DailyLog.step_id == s.id
                                )
                            ).first()
                            status = "完了" if log and log.done else "未完了"
                            memo = log.memo if log and log.memo else (s.memo if s.memo else "なし")
                            summary_parts.append(
                                f"- {s.time} {r.name} - {s.name} ({status}) (メモ: {memo})"
                            )
                else:
                    summary_parts.append("ルーチンステップ: なし")

                results.append(f"{target_date.isoformat()} の活動概要:\n" + "\n".join(summary_parts))
                continue

            errors.append(f"未知のアクション: {action_type}")
        if dirty:
            db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        errors.append(f"操作の適用に失敗しました: {exc}")
        results = []

    return results, errors, modified_ids


@app.get("/api/calendar", name="api_calendar")
def api_calendar(request: Request, db: Session = Depends(get_db)):
    today = datetime.date.today()
    year = int(request.query_params.get("year", today.year))
    month = int(request.query_params.get("month", today.month))

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
            routines = get_weekday_routines(db, weekday)
            total_steps = sum(len(r.steps) for r in routines)

            logs = db.exec(select(DailyLog).where(DailyLog.date == day)).all()
            completed_count = sum(1 for l in logs if l.done)

            custom_tasks = db.exec(select(CustomTask).where(CustomTask.date == day)).all()
            total_steps += len(custom_tasks)
            completed_count += sum(1 for t in custom_tasks if t.done)

            day_log = db.exec(select(DayLog).where(DayLog.date == day)).first()
            has_day_log = bool(day_log and day_log.content and day_log.content.strip())

            week_data.append(
                {
                    "date": day.isoformat(),
                    "day_num": day.day,
                    "is_current_month": is_current_month,
                    "total_routines": len(routines) + len(custom_tasks),
                    "total_steps": total_steps,
                    "completed_steps": completed_count,
                    "has_day_log": has_day_log,
                }
            )
        calendar_data.append(week_data)

    return {
        "calendar_data": calendar_data,
        "year": year,
        "month": month,
        "today": today.isoformat(),
    }


@app.get("/", response_class=HTMLResponse, name="index")
def index(request: Request, db: Session = Depends(get_db)):
    today = datetime.date.today()
    year = int(request.query_params.get("year", today.year))
    month = int(request.query_params.get("month", today.month))

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
            routines = get_weekday_routines(db, weekday)
            total_steps = sum(len(r.steps) for r in routines)

            logs = db.exec(select(DailyLog).where(DailyLog.date == day)).all()
            completed_count = sum(1 for l in logs if l.done)

            custom_tasks = db.exec(select(CustomTask).where(CustomTask.date == day)).all()
            total_steps += len(custom_tasks)
            completed_count += sum(1 for t in custom_tasks if t.done)

            day_log = db.exec(select(DayLog).where(DayLog.date == day)).first()
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

    return template_response(
        request,
        "index.html",
        {"calendar_data": calendar_data, "year": year, "month": month, "today": today},
    )


@app.get("/calendar_partial", response_class=HTMLResponse, name="calendar_partial")
def calendar_partial(request: Request, db: Session = Depends(get_db)):
    today = datetime.date.today()
    year = int(request.query_params.get("year", today.year))
    month = int(request.query_params.get("month", today.month))

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
            routines = get_weekday_routines(db, weekday)
            total_steps = sum(len(r.steps) for r in routines)

            logs = db.exec(select(DailyLog).where(DailyLog.date == day)).all()
            completed_count = sum(1 for l in logs if l.done)

            custom_tasks = db.exec(select(CustomTask).where(CustomTask.date == day)).all()
            total_steps += len(custom_tasks)
            completed_count += sum(1 for t in custom_tasks if t.done)

            day_log = db.exec(select(DayLog).where(DayLog.date == day)).first()
            has_day_log = bool(day_log and day_log.content and day_log.content.strip())

            week_data.append(
                {
                    "date": day,
                    "day_num": day.day,
                    "is_current_month": is_current_month,
                    "total_routines": len(routines) + len(custom_tasks),
                    "total_steps": total_steps,
                    "completed_steps": completed_count,
                    "has_day_log": has_day_log,
                }
            )
        calendar_data.append(week_data)

    return template_response(
        request, "calendar_partial.html", {"calendar_data": calendar_data, "today": today}
    )


@app.get("/embed/calendar", response_class=HTMLResponse, name="embed_calendar")
def embed_calendar(request: Request, db: Session = Depends(get_db)):
    today = datetime.date.today()
    year = int(request.query_params.get("year", today.year))
    month = int(request.query_params.get("month", today.month))

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
            routines = get_weekday_routines(db, weekday)
            total_steps = sum(len(r.steps) for r in routines)

            logs = db.exec(select(DailyLog).where(DailyLog.date == day)).all()
            completed_count = sum(1 for l in logs if l.done)

            custom_tasks = db.exec(select(CustomTask).where(CustomTask.date == day)).all()
            total_steps += len(custom_tasks)
            completed_count += sum(1 for t in custom_tasks if t.done)

            day_log = db.exec(select(DayLog).where(DayLog.date == day)).first()
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

    return template_response(
        request,
        "embed_calendar.html",
        {"calendar_data": calendar_data, "year": year, "month": month, "today": today},
    )


@app.get("/api/day/{date_str}", name="api_day_view")
def api_day_view(date_str: str, db: Session = Depends(get_db)):
    try:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    timeline_items, completion_rate = _get_timeline_data(db, date_obj)
    day_log = db.exec(select(DayLog).where(DayLog.date == date_obj)).first()

    serialized_timeline_items = []
    for item in timeline_items:
        step = item["step"]
        if isinstance(step, dict):
            step_name = step.get("name", "")
            step_category = step.get("category", "Other")
        else:
            step_name = step.name
            step_category = getattr(step, "category", "Other")

        routine = item["routine"]
        if isinstance(routine, dict):
            routine_name = routine.get("name", "")
        else:
            routine_name = routine.name

        log = item["log"]
        if isinstance(log, dict):
            log_done = log.get("done", False)
            log_memo = log.get("memo")
        elif log:
            log_done = log.done
            log_memo = log.memo
        else:
            log_done = False
            log_memo = None

        is_done = item["real_obj"].done if item.get("real_obj") else log_done

        serialized_item = {
            "type": item["type"],
            "time": item["time"],
            "id": item["id"],
            "routine_name": routine_name,
            "step_name": step_name,
            "step_category": step_category,
            "log_done": log_done,
            "log_memo": log_memo,
            "is_done": is_done,
        }
        serialized_timeline_items.append(serialized_item)

    return {
        "date": date_obj.isoformat(),
        "timeline_items": serialized_timeline_items,
        "completion_rate": completion_rate,
        "day_log_content": day_log.content if day_log else None,
    }


@app.api_route("/day/{date_str}", methods=["GET", "POST"], response_class=HTMLResponse, name="day_view")
async def day_view(request: Request, date_str: str, db: Session = Depends(get_db)):
    try:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse(url=str(request.url_for("index")), status_code=303)

    if request.method == "POST":
        form = await request.form()

        if "add_custom_task" in form:
            name = form.get("custom_name")
            time = form.get("custom_time")
            if name:
                ct = CustomTask(date=date_obj, name=name, time=time)
                db.add(ct)
                db.commit()
                flash(request, "カスタムタスクを追加しました。")
            return RedirectResponse(
                url=str(request.url_for("day_view", date_str=date_str)), status_code=303
            )

        if "save_log" in form:
            content = form.get("day_log_content")
            dlog = db.exec(select(DayLog).where(DayLog.date == date_obj)).first()
            if not dlog:
                dlog = DayLog(date=date_obj)
                db.add(dlog)
            dlog.content = content
            db.commit()
            flash(request, "日報を保存しました。")
            return RedirectResponse(
                url=str(request.url_for("day_view", date_str=date_str)), status_code=303
            )

        if "delete_custom_task" in form:
            task_id = form.get("delete_custom_task")
            task = db.get(CustomTask, int(task_id)) if task_id else None
            if task:
                db.delete(task)
                db.commit()
                flash(request, "タスクを削除しました。")
            return RedirectResponse(
                url=str(request.url_for("day_view", date_str=date_str)), status_code=303
            )

        routines = get_weekday_routines(db, date_obj.weekday())
        all_steps = []
        for r in routines:
            all_steps.extend(r.steps)

        for step in all_steps:
            done_key = f"done_{step.id}"
            memo_key = f"memo_{step.id}"
            is_done = form.get(done_key) == "on"
            memo_text = form.get(memo_key, "")

            log = db.exec(
                select(DailyLog).where(DailyLog.date == date_obj, DailyLog.step_id == step.id)
            ).first()
            if not log:
                log = DailyLog(date=date_obj, step_id=step.id)
                db.add(log)

            log.done = is_done
            log.memo = memo_text

        custom_tasks = db.exec(select(CustomTask).where(CustomTask.date == date_obj)).all()
        for task in custom_tasks:
            done_key = f"custom_done_{task.id}"
            memo_key = f"custom_memo_{task.id}"
            is_done = form.get(done_key) == "on"
            memo_text = form.get(memo_key, "")
            task.done = is_done
            task.memo = memo_text

        db.commit()
        flash(request, "進捗を保存しました。")
        return RedirectResponse(
            url=str(request.url_for("day_view", date_str=date_str)), status_code=303
        )

    timeline_items, completion_rate = _get_timeline_data(db, date_obj)
    day_log = db.exec(select(DayLog).where(DayLog.date == date_obj)).first()
    routines = get_weekday_routines(db, date_obj.weekday())

    return template_response(
        request,
        "day.html",
        {
            "date": date_obj,
            "timeline_items": timeline_items,
            "day_log": day_log,
            "completion_rate": completion_rate,
            "routines": routines,
        },
    )


@app.get("/day/{date_str}/timeline", response_class=HTMLResponse, name="day_view_timeline")
def day_view_timeline(request: Request, date_str: str, db: Session = Depends(get_db)):
    try:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Date")

    timeline_items, completion_rate = _get_timeline_data(db, date_obj)

    return template_response(
        request,
        "timeline_partial.html",
        {"date": date_obj, "timeline_items": timeline_items, "completion_rate": completion_rate},
    )


@app.get("/day/{date_str}/log_partial", response_class=HTMLResponse, name="day_view_log_partial")
def day_view_log_partial(request: Request, date_str: str, db: Session = Depends(get_db)):
    try:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Date")

    day_log = db.exec(select(DayLog).where(DayLog.date == date_obj)).first()
    return template_response(request, "log_partial.html", {"day_log": day_log})


@app.get("/api/routines/day/{weekday}", name="api_routines_by_day")
def api_routines_by_day(weekday: int, db: Session = Depends(get_db)):
    routines = get_weekday_routines(db, weekday)
    serialized_routines = []
    for r in routines:
        steps = []
        for s in r.steps:
            steps.append({"id": s.id, "name": s.name, "time": s.time, "category": s.category})
        steps.sort(key=lambda x: x["time"])

        serialized_routines.append(
            {"id": r.id, "name": r.name, "description": r.description, "steps": steps}
        )
    return {"routines": serialized_routines}


@app.get("/api/routines", name="api_routines")
def api_routines(db: Session = Depends(get_db)):
    routines = db.exec(select(Routine)).all()
    serialized_routines = []
    for r in routines:
        steps = []
        for s in r.steps:
            steps.append({"id": s.id, "name": s.name, "time": s.time, "category": s.category})
        serialized_routines.append(
            {"id": r.id, "name": r.name, "days": r.days, "description": r.description, "steps": steps}
        )
    return {"routines": serialized_routines}


@app.get("/routines", response_class=HTMLResponse, name="routines_list")
def routines_list(request: Request, db: Session = Depends(get_db)):
    routines = db.exec(select(Routine)).all()
    return template_response(request, "routines.html", {"routines": routines})


@app.post("/routines/add", name="add_routine")
async def add_routine(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    name = form.get("name")
    days = ",".join(form.getlist("days"))
    desc = form.get("description")
    if name:
        r = Routine(name=name, days=days, description=desc)
        db.add(r)
        db.commit()
    return RedirectResponse(url=str(request.url_for("routines_list")), status_code=303)


@app.post("/routines/{id}/delete", name="delete_routine")
def delete_routine(request: Request, id: int, db: Session = Depends(get_db)):
    r = db.get(Routine, id)
    if not r:
        raise HTTPException(status_code=404, detail="Routine not found")
    db.delete(r)
    db.commit()
    return RedirectResponse(url=str(request.url_for("routines_list")), status_code=303)


@app.post("/routines/{id}/step/add", name="add_step")
async def add_step(request: Request, id: int, db: Session = Depends(get_db)):
    form = await request.form()
    r = db.get(Routine, id)
    if not r:
        raise HTTPException(status_code=404, detail="Routine not found")
    name = form.get("name")
    time = form.get("time")
    category = form.get("category")
    if name:
        s = Step(routine_id=r.id, name=name, time=time, category=category)
        db.add(s)
        db.commit()
    return RedirectResponse(url=str(request.url_for("routines_list")), status_code=303)


@app.post("/steps/{id}/delete", name="delete_step")
def delete_step(request: Request, id: int, db: Session = Depends(get_db)):
    s = db.get(Step, id)
    if not s:
        raise HTTPException(status_code=404, detail="Step not found")
    db.delete(s)
    db.commit()
    return RedirectResponse(url=str(request.url_for("routines_list")), status_code=303)


@app.get("/api/models", name="list_models")
def list_models():
    provider, model, base_url, _ = apply_model_selection("scheduler")
    return {
        "models": current_available_models(),
        "current": {"provider": provider, "model": model, "base_url": base_url},
    }


@app.post("/model_settings", name="update_model_settings")
async def update_model_settings(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    selection = payload.get("selection") if "selection" in payload else payload
    if isinstance(selection, dict) and "scheduler" in selection:
        selection = selection.get("scheduler")
    if selection is not None and not isinstance(selection, dict):
        raise HTTPException(status_code=400, detail="selection must be an object")

    try:
        provider, model, base_url, _ = update_override(selection if selection else None)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"モデル設定の更新に失敗しました: {exc}")
    return {"status": "ok", "applied": {"provider": provider, "model": model, "base_url": base_url}}


@app.api_route("/api/chat/history", methods=["GET", "DELETE"], name="manage_chat_history")
async def manage_chat_history(request: Request, db: Session = Depends(get_db)):
    if request.method == "DELETE":
        try:
            db.exec(delete(ChatHistory))
            db.commit()
            return {"status": "cleared"}
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=str(e))

    history = db.exec(select(ChatHistory).order_by(ChatHistory.timestamp)).all()
    return {
        "history": [
            {"role": h.role, "content": h.content, "timestamp": h.timestamp.isoformat()}
            for h in history
        ]
    }


@app.post("/api/conversations/review", name="review_conversation_history")
async def review_conversation_history(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    raw_history = payload.get("history")
    if raw_history is None:
        raw_history = payload.get("messages")

    history_messages = _normalise_history_messages(raw_history)
    if not history_messages:
        raise HTTPException(status_code=400, detail="history must be a non-empty array")

    today = datetime.date.today()
    context = _build_scheduler_context(db, today)

    try:
        review = _call_conversation_review(history_messages, context)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"会話履歴の分析に失敗しました: {exc}")

    actions = review.get("actions") if isinstance(review.get("actions"), list) else []
    results, errors, modified_ids = _apply_actions(db, actions, today)
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
        if history_messages and history_messages[-1]["role"] == "user":
            last_user_msg = history_messages[-1]["content"]

        summary_messages = [
            {"role": "system", "content": summary_system_prompt},
            {
                "role": "user",
                "content": f"直近のユーザー発言: {last_user_msg}\n\n{result_text}\n\n元のアシスタントの応答案: {base_reply}",
            },
        ]

        try:
            resp = summary_client.create(messages=summary_messages, temperature=0.7, max_tokens=1000)
            final_reply = _content_to_text(resp.choices[0].message.content)
        except Exception:
            reply_parts = []
            if base_reply:
                reply_parts.append(base_reply)
            if results:
                reply_parts.append("実行結果:\n" + "\n".join(f"- {item}" for item in results))
            if errors:
                reply_parts.append("エラー:\n" + "\n".join(f"- {err}" for err in errors))
            final_reply = "\n\n".join(reply_parts)
    else:
        final_reply = base_reply

    return {
        "action_required": bool(review.get("action_required") or actions),
        "action_taken": action_taken,
        "actions": actions,
        "results": [],
        "_original_results": results,
        "errors": errors,
        "modified_ids": modified_ids,
        "should_reply": bool(review.get("should_reply") or final_reply),
        "reply": final_reply,
        "notes": review.get("notes") if isinstance(review.get("notes"), str) else "",
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
        except Exception as e:
            db.rollback()
            print(f"Failed to save user message: {e}")

    today = datetime.date.today()
    context = _build_scheduler_context(db, today)

    try:
        reply_text, actions = call_scheduler_llm(formatted_messages, context)
    except Exception as exc:
        return {"reply": f"LLM 呼び出しに失敗しました: {exc}", "should_refresh": False, "modified_ids": []}

    results, errors, modified_ids = _apply_actions(db, actions, today)

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
            "2. **分かりやすく**: 実行結果の羅列（「カスタムタスク[2]...」のような形式）は避け、人間が読みやすい文章に整形してください。\n"
            "   - 例: 「12月10日の9時から『カラオケ』の予定が入っていますね！楽しんできてください🎤」\n"
            "3. **エラーへの対応**: エラーがある場合は、優しくその旨を伝え、どうすればよいか（もし分かれば）示唆してください。\n"
            "4. **元の文脈を維持**: ユーザーの元の発言に対する返答として自然になるようにしてください。\n"
        )

        summary_messages = [
            {"role": "system", "content": summary_system_prompt},
            {"role": "user", "content": f"ユーザーの発言: {user_message}\n\n{result_text}"},
        ]

        try:
            resp = summary_client.create(messages=summary_messages, temperature=0.7, max_tokens=1000)
            final_reply = _content_to_text(resp.choices[0].message.content)

        except Exception as e:
            final_reply = (reply_text or "") + "\n\n" + result_text
            print(f"Summary LLM failed: {e}")

    else:
        final_reply = reply_text if reply_text else "了解しました。"

    if save_history:
        try:
            db.add(ChatHistory(role="assistant", content=final_reply))
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Failed to save assistant message: {e}")

    return {"reply": final_reply, "should_refresh": (len(results) > 0), "modified_ids": modified_ids}


@app.post("/api/chat", name="chat")
async def chat(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages must be a list")

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
        raise HTTPException(status_code=400, detail="last message must be from user")

    recent_messages = formatted_messages[-10:]

    result = process_chat_request(db, recent_messages)

    return result


@app.get("/evaluation", response_class=HTMLResponse, name="evaluation_page")
def evaluation_page(request: Request):
    return template_response(request, "evaluation.html", {})


@app.post("/api/evaluation/chat", name="evaluation_chat")
async def evaluation_chat(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages must be a list")

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
        raise HTTPException(status_code=400, detail="last message must be from user")

    today = datetime.date.today()
    context = _build_scheduler_context(db, today)

    try:
        reply_text, actions = call_scheduler_llm(formatted_messages, context)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"LLM Error: {exc}")

    results, errors, modified_ids = _apply_actions(db, actions, today)

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
            {"role": "user", "content": f"ユーザーの発言: {user_message}\n\n{result_text}"},
        ]
        try:
            resp = summary_client.create(messages=summary_messages, temperature=0.7, max_tokens=1000)
            final_reply = _content_to_text(resp.choices[0].message.content)
        except Exception:
            final_reply = (reply_text or "") + "\n\n" + result_text

    return {"reply": final_reply, "raw_reply": reply_text, "actions": actions, "results": results, "errors": errors}


@app.post("/api/evaluation/reset", name="evaluation_reset")
def evaluation_reset(db: Session = Depends(get_db)):
    try:
        db.exec(delete(DailyLog))
        db.exec(delete(CustomTask))
        db.exec(delete(Step))
        db.exec(delete(Routine))
        db.exec(delete(DayLog))
        db.commit()
        return {"status": "ok", "message": "Scheduler data cleared."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/evaluation/seed", name="evaluation_seed")
async def evaluation_seed(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    date_str = payload.get("date") or request.query_params.get("date")
    if date_str:
        target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        target_date = datetime.date.today()

    messages = _seed_evaluation_data(db, target_date, target_date)
    return {"status": "ok", "message": "; ".join(messages)}


@app.post("/api/evaluation/seed_period", name="evaluation_seed_period")
async def evaluation_seed_period(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    start_date_str = payload.get("start_date") or request.query_params.get("start_date")
    end_date_str = payload.get("end_date") or request.query_params.get("end_date")

    if not start_date_str or not end_date_str:
        raise HTTPException(status_code=400, detail="start_date and end_date are required")

    start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()

    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start_date cannot be after end_date")

    messages = _seed_evaluation_data(db, start_date, end_date)
    return {"status": "ok", "message": "; ".join(messages)}


def _seed_evaluation_data(db: Session, start_date: datetime.date, end_date: datetime.date):
    messages = []

    routine_name = "Daily Routine"
    daily_routine = db.exec(select(Routine).where(Routine.name == routine_name)).first()
    if not daily_routine:
        daily_routine = Routine(
            name=routine_name, days="0,1,2,3,4,5,6", description="General daily habits"
        )
        db.add(daily_routine)
        db.flush()

        steps_data = [
            ("07:00", "Wake up", "Lifestyle"),
            ("08:00", "Breakfast", "Lifestyle"),
            ("09:00", "Check Emails", "Browser"),
            ("12:00", "Lunch", "Lifestyle"),
            ("18:00", "Workout", "Lifestyle"),
            ("22:00", "Read Book", "Lifestyle"),
        ]
        for time, name, category in steps_data:
            s = Step(routine_id=daily_routine.id, name=name, time=time, category=category)
            db.add(s)
        messages.append(f"Seeded Routine '{routine_name}'")

    current_date = start_date
    while current_date <= end_date:
        db.exec(delete(DailyLog).where(DailyLog.date == current_date))
        db.exec(delete(CustomTask).where(CustomTask.date == current_date))
        db.exec(delete(DayLog).where(DayLog.date == current_date))
        messages.append(f"Cleared existing data for {current_date.isoformat()}")

        log_content = f"これは{current_date.isoformat()}の評価用日報です。今日の気分は最高です！"
        db.add(DayLog(date=current_date, content=log_content))
        messages.append(f"Seeded DayLog for {current_date.isoformat()}")

        db.add(
            CustomTask(
                date=current_date,
                name=f"ミーティング ({current_date.day}日)",
                time="10:00",
                memo="重要な議題",
            )
        )
        db.add(
            CustomTask(
                date=current_date,
                name=f"レポート作成 ({current_date.day}日)",
                time="14:00",
                memo="期限は明日",
            )
        )
        messages.append(f"Seeded Custom Tasks for {current_date.isoformat()}")

        if daily_routine:
            all_steps = db.exec(
                select(Step).where(Step.routine_id == daily_routine.id)
            ).all()
            if all_steps:
                if len(all_steps) >= 1:
                    log_entry = DailyLog(
                        date=current_date, step_id=all_steps[0].id, done=True, memo="朝の活動完了"
                    )
                    db.add(log_entry)
                    messages.append(
                        f"Marked step '{all_steps[0].name}' as done for {current_date.isoformat()}"
                    )
                if len(all_steps) >= 3:
                    log_entry = DailyLog(
                        date=current_date, step_id=all_steps[2].id, done=True, memo="メールチェック完了"
                    )
                    db.add(log_entry)
                    messages.append(
                        f"Marked step '{all_steps[2].name}' as done for {current_date.isoformat()}"
                    )

        current_date += datetime.timedelta(days=1)

    db.commit()
    return messages


@app.post("/api/add_sample_data", name="add_sample_data")
def add_sample_data(db: Session = Depends(get_db)):
    try:
        today = datetime.date.today()
        messages = []

        days_behind = (today.weekday() - 4) % 7
        if days_behind <= 0:
            days_behind += 7
        last_friday = today - datetime.timedelta(days=days_behind)

        log = db.exec(select(DayLog).where(DayLog.date == last_friday)).first()
        if not log:
            log = DayLog(
                date=last_friday, content="先週の金曜日はとても良い天気でした。プロジェクトの進捗も順調でした。"
            )
            db.add(log)
            messages.append(f"Seeded DayLog for {last_friday}")

        routine_name = "Daily Routine"
        daily_routine = db.exec(select(Routine).where(Routine.name == routine_name)).first()
        if not daily_routine:
            daily_routine = Routine(
                name=routine_name, days="0,1,2,3,4,5,6", description="General daily habits"
            )
            db.add(daily_routine)
            db.flush()

            steps_data = [("07:00", "Wake up", "Lifestyle"), ("08:00", "Breakfast", "Lifestyle"), ("09:00", "Check Emails", "Browser")]
            for time, name, category in steps_data:
                s = Step(routine_id=daily_routine.id, name=name, time=time, category=category)
                db.add(s)
            messages.append(f"Seeded Routine '{routine_name}'")

        task_name = "Buy Milk"
        if not db.exec(
            select(CustomTask).where(CustomTask.date == today, CustomTask.name == task_name)
        ).first():
            db.add(CustomTask(date=today, name=task_name, time="18:00", memo="Low fat"))
            messages.append(f"Seeded Task '{task_name}' for Today ({today})")

        tomorrow = today + datetime.timedelta(days=1)
        tasks_tomorrow = [("13:00", "Lunch with Alice", "At the Italian place"), ("15:00", "Doctor Appointment", "Bring ID")]
        for time, name, memo in tasks_tomorrow:
            if not db.exec(
                select(CustomTask).where(CustomTask.date == tomorrow, CustomTask.name == name)
            ).first():
                db.add(CustomTask(date=tomorrow, name=name, time=time, memo=memo))
                messages.append(f"Seeded Task '{name}' for Tomorrow ({tomorrow})")

        day_after = today + datetime.timedelta(days=2)
        task_name_da = "Gym"
        if not db.exec(
            select(CustomTask).where(
                CustomTask.date == day_after, CustomTask.name == task_name_da
            )
        ).first():
            db.add(CustomTask(date=day_after, name=task_name_da, time="19:00", memo="Leg day"))
            messages.append(f"Seeded Task '{task_name_da}' for Day after Tomorrow ({day_after})")

        db.commit()

        if not messages:
            return {"status": "ok", "message": "Data already exists, nothing new seeded."}

        return {"status": "ok", "message": "; ".join(messages)}

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/evaluation/log", name="evaluation_log")
async def evaluation_log(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
    except Exception:
        data = {}
    try:
        res = EvaluationResult(
            model_name=data.get("model_name"),
            task_prompt=data.get("task_prompt"),
            agent_reply=data.get("agent_reply"),
            tool_calls=json.dumps(data.get("tool_calls", [])),
            is_success=data.get("is_success"),
            comments=data.get("comments"),
        )
        db.add(res)
        db.commit()
        return {"status": "ok"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/evaluation/history", name="evaluation_history")
def evaluation_history(db: Session = Depends(get_db)):
    results = db.exec(
        select(EvaluationResult).order_by(EvaluationResult.timestamp.desc())
    ).all()
    data = []
    for r in results:
        data.append(
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "model_name": r.model_name,
                "task_prompt": r.task_prompt,
                "is_success": r.is_success,
            }
        )
    return {"history": data}
