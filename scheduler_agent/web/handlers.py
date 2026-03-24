"""HTTP handler implementations used by compatibility wrappers."""

from __future__ import annotations

import calendar
import datetime
import json
import logging
from typing import Any, Callable, Dict, List

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete as sa_delete
from sqlmodel import Session, select

from model_selection import apply_model_selection, current_available_models, update_override
from scheduler_agent.core.config import dangerous_evaluation_api_enabled, get_max_input_chars
from scheduler_agent.models import (
    ChatHistory,
    CustomTask,
    DailyLog,
    DayLog,
    EvaluationResult,
    Routine,
    Step,
)
from scheduler_agent.web.error_handling import raise_internal_server_error
from scheduler_agent.web.request_context import get_guest_id_from_request

logger = logging.getLogger("scheduler_agent.web.handlers")


def _resolve_guest_id(request: Request | None) -> str:
    if request is None:
        return "default"
    state = getattr(request, "state", None)
    if state is not None and getattr(state, "guest_context", None):
        return get_guest_id_from_request(request)
    test_guest_id = getattr(request, "guest_id", None)
    if isinstance(test_guest_id, str) and test_guest_id.strip():
        return test_guest_id.strip()
    return get_guest_id_from_request(request)


def _call_get_weekday_routines(get_weekday_routines_fn, db: Session, weekday: int, guest_id: str):
    try:
        return get_weekday_routines_fn(db, weekday, guest_id=guest_id)
    except TypeError:
        return get_weekday_routines_fn(db, weekday)


def _call_get_timeline_data(get_timeline_data_fn, db: Session, date_obj: datetime.date, guest_id: str):
    try:
        return get_timeline_data_fn(db, date_obj, guest_id=guest_id)
    except TypeError:
        return get_timeline_data_fn(db, date_obj)


def _call_process_chat_request(process_chat_request_fn, db: Session, messages: List[Dict[str, str]], guest_id: str):
    try:
        return process_chat_request_fn(db, messages, guest_id=guest_id)
    except TypeError:
        return process_chat_request_fn(db, messages)


def _call_run_scheduler_multi_step(
    run_scheduler_multi_step_fn,
    db: Session,
    messages: List[Dict[str, str]],
    today: datetime.date,
    guest_id: str,
):
    try:
        return run_scheduler_multi_step_fn(db, messages, today, guest_id=guest_id)
    except TypeError:
        return run_scheduler_multi_step_fn(db, messages, today)


def _call_seed_evaluation_data(seed_evaluation_data_fn, db: Session, start_date: datetime.date, end_date: datetime.date, guest_id: str):
    try:
        return seed_evaluation_data_fn(db, start_date, end_date, guest_id=guest_id)
    except TypeError:
        return seed_evaluation_data_fn(db, start_date, end_date)


def _call_seed_sample_data(seed_sample_data_fn, db: Session, guest_id: str):
    try:
        return seed_sample_data_fn(db, guest_id=guest_id)
    except TypeError:
        return seed_sample_data_fn(db)


def _require_dangerous_eval_api_enabled() -> None:
    if dangerous_evaluation_api_enabled():
        return
    raise HTTPException(status_code=403, detail="This endpoint is disabled in production.")


def _scoped_delete_statement(delete_fn, model: Any, guest_id: str):
    statement = delete_fn(model)
    where_fn = getattr(statement, "where", None)
    if callable(where_fn):
        return where_fn(getattr(model, "guest_id") == guest_id)
    return statement


# 日本語: セッション内フラッシュメッセージをAPI形式で返す / English: Return session flash messages as API payload
def api_flash(
    request: Request,
    *,
    pop_flashed_messages_fn,
):
    return {"messages": pop_flashed_messages_fn(request)}


# 日本語: 月間カレンダー表示用の集計データを生成 / English: Build monthly calendar aggregate data for UI
def api_calendar(
    request: Request,
    db: Session,
    *,
    get_weekday_routines_fn,
):
    guest_id = _resolve_guest_id(request)
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
            # 日本語: 各日についてルーチン・タスク・日報のサマリーを算出 / English: Aggregate routines, tasks, and day-log summary per date
            is_current_month = day.month == month

            weekday = day.weekday()
            routines = _call_get_weekday_routines(get_weekday_routines_fn, db, weekday, guest_id)
            total_steps = sum(len(r.steps) for r in routines)

            logs = db.exec(
                select(DailyLog).where(DailyLog.date == day, DailyLog.guest_id == guest_id)
            ).all()
            completed_count = sum(1 for log in logs if log.done)

            custom_tasks = db.exec(
                select(CustomTask).where(CustomTask.date == day, CustomTask.guest_id == guest_id)
            ).all()
            total_steps += len(custom_tasks)
            completed_count += sum(1 for task in custom_tasks if task.done)

            day_log = db.exec(select(DayLog).where(DayLog.date == day, DayLog.guest_id == guest_id)).first()
            has_day_log = bool(day_log and day_log.content and day_log.content.strip())

            week_data.append(
                {
                    "date": day.isoformat(),
                    "day_num": day.day,
                    "is_current_month": is_current_month,
                    "routine_count": len(routines),
                    "custom_task_count": len(custom_tasks),
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


# 日本語: SPA のトップページを返す / English: Render SPA index page
def index(request: Request, *, template_response_fn):
    return template_response_fn(request, "spa.html", {"page_id": "index"})


# 日本語: エージェント結果ページを返す / English: Render agent-result page
def agent_result(request: Request, *, template_response_fn):
    return template_response_fn(request, "spa.html", {"page_id": "agent-result"})


# 日本語: /agent-result/day の表示とPOST更新を処理 / English: Handle view/update flow for /agent-result/day
async def agent_day_view(
    request: Request,
    date_str: str,
    db: Session,
    *,
    get_weekday_routines_fn,
    flash_fn,
    template_response_fn,
):
    guest_id = _resolve_guest_id(request)
    try:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse(url=str(request.url_for("agent_result")), status_code=303)

    if request.method == "POST":
        form = await request.form()

        # 日本語: カスタムタスク追加フォーム / English: Custom task creation form branch
        if "add_custom_task" in form:
            name = form.get("custom_name")
            time_value = form.get("custom_time")
            if name:
                task = CustomTask(guest_id=guest_id, date=date_obj, name=name, time=time_value)
                db.add(task)
                db.commit()
                flash_fn(request, "カスタムタスクを追加しました。")
            return RedirectResponse(
                url=str(request.url_for("agent_day_view", date_str=date_str)), status_code=303
            )

        # 日本語: 1日メモ(日報)保存フォーム / English: Day-log save form branch
        if "save_log" in form:
            content = form.get("day_log_content")
            day_log = db.exec(
                select(DayLog).where(DayLog.date == date_obj, DayLog.guest_id == guest_id)
            ).first()
            if not day_log:
                day_log = DayLog(guest_id=guest_id, date=date_obj)
                db.add(day_log)
            day_log.content = content
            db.commit()
            flash_fn(request, "日報を保存しました。")
            return RedirectResponse(
                url=str(request.url_for("agent_day_view", date_str=date_str)), status_code=303
            )

        # 日本語: カスタムタスク削除フォーム / English: Custom task delete form branch
        if "delete_custom_task" in form:
            task_id = form.get("delete_custom_task")
            task = db.get(CustomTask, int(task_id)) if task_id else None
            if task and task.guest_id != guest_id:
                task = None
            if task:
                db.delete(task)
                db.commit()
                flash_fn(request, "タスクを削除しました。")
            return RedirectResponse(
                url=str(request.url_for("agent_day_view", date_str=date_str)), status_code=303
            )

        # 日本語: ルーチンステップとカスタムタスクのチェック状態を一括保存 / English: Persist completion/memo states for routine steps and custom tasks
        routines = _call_get_weekday_routines(get_weekday_routines_fn, db, date_obj.weekday(), guest_id)
        all_steps = []
        for routine in routines:
            all_steps.extend(routine.steps)

        for step in all_steps:
            done_key = f"done_{step.id}"
            memo_key = f"memo_{step.id}"
            is_done = form.get(done_key) == "on"
            memo_text = form.get(memo_key, "")

            log = db.exec(
                select(DailyLog).where(
                    DailyLog.date == date_obj,
                    DailyLog.step_id == step.id,
                    DailyLog.guest_id == guest_id,
                )
            ).first()
            if not log:
                log = DailyLog(guest_id=guest_id, date=date_obj, step_id=step.id)
                db.add(log)

            log.done = is_done
            log.memo = memo_text

        custom_tasks = db.exec(
            select(CustomTask).where(CustomTask.date == date_obj, CustomTask.guest_id == guest_id)
        ).all()
        for task in custom_tasks:
            done_key = f"custom_done_{task.id}"
            memo_key = f"custom_memo_{task.id}"
            is_done = form.get(done_key) == "on"
            memo_text = form.get(memo_key, "")
            task.done = is_done
            task.memo = memo_text

        db.commit()
        flash_fn(request, "進捗を保存しました。")
        return RedirectResponse(
            url=str(request.url_for("agent_day_view", date_str=date_str)), status_code=303
        )

    return template_response_fn(request, "spa.html", {"page_id": "agent-day"})


# 日本語: 埋め込み用カレンダーページ / English: Embedded calendar page
def embed_calendar(request: Request, *, template_response_fn):
    return template_response_fn(request, "spa.html", {"page_id": "embed-calendar"})


# 日本語: 指定日のタイムラインAPI / English: Timeline API for a specific day
def api_day_view(
    date_str: str,
    db: Session,
    *,
    get_timeline_data_fn,
    request: Request | None = None,
):
    guest_id = _resolve_guest_id(request)
    try:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    timeline_items, completion_rate = _call_get_timeline_data(get_timeline_data_fn, db, date_obj, guest_id)
    day_log = db.exec(select(DayLog).where(DayLog.date == date_obj, DayLog.guest_id == guest_id)).first()

    serialized_timeline_items = []
    for item in timeline_items:
        # 日本語: ORMオブジェクト/辞書どちらでも同一形式に正規化 / English: Normalize both ORM objects and dict-like items into one schema
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
        "weekday": date_obj.weekday(),
        "day_name": date_obj.strftime("%A"),
        "date_display": date_obj.strftime("%Y.%m.%d"),
        "timeline_items": serialized_timeline_items,
        "completion_rate": completion_rate,
        "day_log_content": day_log.content if day_log else None,
    }


# 日本語: /day の表示とPOST更新を処理 / English: Handle view/update flow for /day endpoint
async def day_view(
    request: Request,
    date_str: str,
    db: Session,
    *,
    get_weekday_routines_fn,
    flash_fn,
    template_response_fn,
):
    guest_id = _resolve_guest_id(request)
    try:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse(url=str(request.url_for("index")), status_code=303)

    if request.method == "POST":
        form = await request.form()

        # 日本語: カスタムタスク追加フォーム / English: Custom task creation form branch
        if "add_custom_task" in form:
            name = form.get("custom_name")
            time_value = form.get("custom_time")
            if name:
                task = CustomTask(guest_id=guest_id, date=date_obj, name=name, time=time_value)
                db.add(task)
                db.commit()
                flash_fn(request, "カスタムタスクを追加しました。")
            return RedirectResponse(
                url=str(request.url_for("day_view", date_str=date_str)), status_code=303
            )

        # 日本語: 日報保存フォーム / English: Day-log save form branch
        if "save_log" in form:
            content = form.get("day_log_content")
            day_log = db.exec(
                select(DayLog).where(DayLog.date == date_obj, DayLog.guest_id == guest_id)
            ).first()
            if not day_log:
                day_log = DayLog(guest_id=guest_id, date=date_obj)
                db.add(day_log)
            day_log.content = content
            db.commit()
            flash_fn(request, "日報を保存しました。")
            return RedirectResponse(
                url=str(request.url_for("day_view", date_str=date_str)), status_code=303
            )

        # 日本語: カスタムタスク削除フォーム / English: Custom task delete form branch
        if "delete_custom_task" in form:
            task_id = form.get("delete_custom_task")
            task = db.get(CustomTask, int(task_id)) if task_id else None
            if task and task.guest_id != guest_id:
                task = None
            if task:
                db.delete(task)
                db.commit()
                flash_fn(request, "タスクを削除しました。")
            return RedirectResponse(
                url=str(request.url_for("day_view", date_str=date_str)), status_code=303
            )

        # 日本語: 画面全体の進捗入力を日次ログへ反映 / English: Persist full-page progress inputs into daily logs
        routines = _call_get_weekday_routines(get_weekday_routines_fn, db, date_obj.weekday(), guest_id)
        all_steps = []
        for routine in routines:
            all_steps.extend(routine.steps)

        for step in all_steps:
            done_key = f"done_{step.id}"
            memo_key = f"memo_{step.id}"
            is_done = form.get(done_key) == "on"
            memo_text = form.get(memo_key, "")

            log = db.exec(
                select(DailyLog).where(
                    DailyLog.date == date_obj,
                    DailyLog.step_id == step.id,
                    DailyLog.guest_id == guest_id,
                )
            ).first()
            if not log:
                log = DailyLog(guest_id=guest_id, date=date_obj, step_id=step.id)
                db.add(log)

            log.done = is_done
            log.memo = memo_text

        custom_tasks = db.exec(
            select(CustomTask).where(CustomTask.date == date_obj, CustomTask.guest_id == guest_id)
        ).all()
        for task in custom_tasks:
            done_key = f"custom_done_{task.id}"
            memo_key = f"custom_memo_{task.id}"
            is_done = form.get(done_key) == "on"
            memo_text = form.get(memo_key, "")
            task.done = is_done
            task.memo = memo_text

        db.commit()
        flash_fn(request, "進捗を保存しました。")
        return RedirectResponse(
            url=str(request.url_for("day_view", date_str=date_str)), status_code=303
        )

    return template_response_fn(request, "spa.html", {"page_id": "day"})


# 日本語: 曜日指定のルーチン一覧API / English: Routine list API filtered by weekday
def api_routines_by_day(weekday: int, db: Session, *, get_weekday_routines_fn, request: Request | None = None):
    guest_id = _resolve_guest_id(request)
    routines = _call_get_weekday_routines(get_weekday_routines_fn, db, weekday, guest_id)
    serialized_routines = []
    for routine in routines:
        steps = []
        for step in routine.steps:
            steps.append({"id": step.id, "name": step.name, "time": step.time, "category": step.category})
        steps.sort(key=lambda item: item["time"])

        serialized_routines.append(
            {"id": routine.id, "name": routine.name, "description": routine.description, "steps": steps}
        )
    return {"routines": serialized_routines}


# 日本語: 全ルーチン一覧API / English: API for listing all routines
def api_routines(db: Session, request: Request | None = None):
    guest_id = _resolve_guest_id(request)
    routines = db.exec(select(Routine).where(Routine.guest_id == guest_id)).all()
    serialized_routines = []
    for routine in routines:
        steps = []
        for step in routine.steps:
            steps.append({"id": step.id, "name": step.name, "time": step.time, "category": step.category})
        serialized_routines.append(
            {
                "id": routine.id,
                "name": routine.name,
                "days": routine.days,
                "description": routine.description,
                "steps": steps,
            }
        )
    return {"routines": serialized_routines}


# 日本語: ルーチン管理画面 / English: Routine management page
def routines_list(request: Request, *, template_response_fn):
    return template_response_fn(request, "spa.html", {"page_id": "routines"})


# 日本語: ルーチン作成POST / English: Create routine from form POST
async def add_routine(request: Request, db: Session):
    guest_id = _resolve_guest_id(request)
    form = await request.form()
    name = form.get("name")
    days = ",".join(form.getlist("days"))
    desc = form.get("description")
    if name:
        routine = Routine(guest_id=guest_id, name=name, days=days, description=desc)
        db.add(routine)
        db.commit()
    return RedirectResponse(url=str(request.url_for("routines_list")), status_code=303)


# 日本語: ルーチン削除POST / English: Delete routine from form POST
def delete_routine(request: Request, id: int, db: Session):
    guest_id = _resolve_guest_id(request)
    routine = db.get(Routine, id)
    if not routine or routine.guest_id != guest_id:
        raise HTTPException(status_code=404, detail="Routine not found")
    db.delete(routine)
    db.commit()
    return RedirectResponse(url=str(request.url_for("routines_list")), status_code=303)


# 日本語: ルーチンへのステップ追加POST / English: Add step to routine via form POST
async def add_step(request: Request, id: int, db: Session):
    guest_id = _resolve_guest_id(request)
    form = await request.form()
    routine = db.get(Routine, id)
    if not routine or routine.guest_id != guest_id:
        raise HTTPException(status_code=404, detail="Routine not found")
    name = form.get("name")
    time_value = form.get("time")
    category = form.get("category")
    if name:
        step = Step(
            guest_id=guest_id,
            routine_id=routine.id,
            name=name,
            time=time_value,
            category=category,
        )
        db.add(step)
        db.commit()
    return RedirectResponse(url=str(request.url_for("routines_list")), status_code=303)


# 日本語: ステップ削除POST / English: Delete step via form POST
def delete_step(request: Request, id: int, db: Session):
    guest_id = _resolve_guest_id(request)
    step = db.get(Step, id)
    if not step or step.guest_id != guest_id:
        raise HTTPException(status_code=404, detail="Step not found")
    db.delete(step)
    db.commit()
    return RedirectResponse(url=str(request.url_for("routines_list")), status_code=303)


# 日本語: 利用可能モデルと現在選択を返す / English: Return available models and current selection
def list_models(*, apply_model_selection_fn=apply_model_selection, current_available_models_fn=current_available_models):
    provider, model, base_url, _ = apply_model_selection_fn("scheduler")
    return {
        "models": current_available_models_fn(),
        "current": {"provider": provider, "model": model, "base_url": base_url},
    }


# 日本語: モデル選択の上書き設定を更新 / English: Update in-memory model override selection
async def update_model_settings(request: Request, *, update_override_fn=update_override):
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
        provider, model, base_url, _ = update_override_fn(selection if selection else None)
    except Exception as exc:
        raise_internal_server_error("モデル設定の更新に失敗しました。", exc=exc)
    return {"status": "ok", "applied": {"provider": provider, "model": model, "base_url": base_url}}


# 日本語: チャット履歴の取得・削除API / English: GET/DELETE handler for chat history
async def manage_chat_history(
    request: Request,
    db: Session,
    *,
    extract_execution_trace_fn,
    delete_fn=sa_delete,
):
    guest_id = _resolve_guest_id(request)
    if request.method == "DELETE":
        # 日本語: 全履歴クリア / English: Clear all chat history rows
        try:
            db.exec(_scoped_delete_statement(delete_fn, ChatHistory, guest_id))
            db.commit()
            return {"status": "cleared"}
        except Exception as exc:
            db.rollback()
            raise_internal_server_error("チャット履歴の削除に失敗しました。", exc=exc)

    history = db.exec(
        select(ChatHistory)
        .where(ChatHistory.guest_id == guest_id)
        .order_by(ChatHistory.timestamp)
    ).all()
    serialized_history = []
    for item in history:
        # 日本語: 保存時に埋め込んだ execution trace を展開 / English: Extract embedded execution trace from stored content
        clean_content, execution_trace = extract_execution_trace_fn(item.content)
        serialized_history.append(
            {
                "role": item.role,
                "content": clean_content,
                "timestamp": item.timestamp.isoformat(),
                "execution_trace": execution_trace,
            }
        )
    return {"history": serialized_history}


# 日本語: チャットAPI本体 / English: Main chat API handler
async def chat(request: Request, db: Session, *, process_chat_request_fn):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages must be a list")

    formatted_messages = []
    for msg in messages:
        # 日本語: role/content が妥当なメッセージのみ通す / English: Keep only messages with valid role/content
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str):
            continue
        formatted_messages.append({"role": role, "content": content})

    if not formatted_messages or formatted_messages[-1]["role"] != "user":
        raise HTTPException(status_code=400, detail="last message must be from user")

    max_input_chars = get_max_input_chars()
    last_user_content = formatted_messages[-1]["content"]
    if len(last_user_content) > max_input_chars:
        raise HTTPException(
            status_code=400,
            detail=f"input exceeds max length ({max_input_chars} characters)",
        )

    recent_messages = formatted_messages[-10:]

    # 日本語: 最新10件のみで推論負荷を制御 / English: Limit context to recent 10 messages
    guest_id = _resolve_guest_id(request)
    return _call_process_chat_request(process_chat_request_fn, db, recent_messages, guest_id)


# 日本語: 評価画面 / English: Evaluation page
def evaluation_page(request: Request, *, template_response_fn):
    return template_response_fn(request, "spa.html", {"page_id": "evaluation"})


# 日本語: 評価チャットAPI（履歴保存なし） / English: Evaluation chat endpoint (no persistent history)
async def evaluation_chat(
    request: Request,
    db: Session,
    *,
    run_scheduler_multi_step_fn,
    build_final_reply_fn,
):
    _require_dangerous_eval_api_enabled()
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
    guest_id = _resolve_guest_id(request)
    execution = _call_run_scheduler_multi_step(
        run_scheduler_multi_step_fn,
        db,
        formatted_messages,
        today,
        guest_id,
    )
    reply_text = execution.get("reply_text", "")
    results = execution.get("results", [])
    errors = execution.get("errors", [])
    actions = execution.get("actions", [])

    user_message = formatted_messages[-1]["content"]
    final_reply = build_final_reply_fn(
        user_message=user_message,
        reply_text=reply_text,
        results=results,
        errors=errors,
    )

    return {
        "reply": final_reply,
        "raw_reply": reply_text,
        "actions": actions,
        "results": results,
        "errors": errors,
        "execution_trace": execution.get("execution_trace", []),
    }


# 日本語: 評価用データを初期化 / English: Reset scheduler data for evaluation runs
def evaluation_reset(request: Request | None, db: Session, *, delete_fn=sa_delete):
    _require_dangerous_eval_api_enabled()
    try:
        target_guest_id = _resolve_guest_id(request)
        db.exec(_scoped_delete_statement(delete_fn, DailyLog, target_guest_id))
        db.exec(_scoped_delete_statement(delete_fn, CustomTask, target_guest_id))
        db.exec(_scoped_delete_statement(delete_fn, Step, target_guest_id))
        db.exec(_scoped_delete_statement(delete_fn, Routine, target_guest_id))
        db.exec(_scoped_delete_statement(delete_fn, DayLog, target_guest_id))
        db.exec(_scoped_delete_statement(delete_fn, EvaluationResult, target_guest_id))
        db.commit()
        return {"status": "ok", "message": "Scheduler data cleared."}
    except Exception as exc:
        db.rollback()
        raise_internal_server_error("評価データの初期化に失敗しました。", exc=exc)


# 日本語: 単日シード投入 / English: Seed evaluation data for a single date
async def evaluation_seed(request: Request, db: Session, *, seed_evaluation_data_fn):
    _require_dangerous_eval_api_enabled()
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    date_str = payload.get("date") or request.query_params.get("date")
    if date_str:
        target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        target_date = datetime.date.today()

    guest_id = _resolve_guest_id(request)
    messages = _call_seed_evaluation_data(seed_evaluation_data_fn, db, target_date, target_date, guest_id)
    return {"status": "ok", "message": "; ".join(messages)}


# 日本語: 期間シード投入 / English: Seed evaluation data for a date range
async def evaluation_seed_period(request: Request, db: Session, *, seed_evaluation_data_fn):
    _require_dangerous_eval_api_enabled()
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

    guest_id = _resolve_guest_id(request)
    messages = _call_seed_evaluation_data(seed_evaluation_data_fn, db, start_date, end_date, guest_id)
    return {"status": "ok", "message": "; ".join(messages)}


# 日本語: サンプルデータ投入API / English: Seed sample data endpoint
def add_sample_data(request: Request | None, db: Session, *, seed_sample_data_fn):
    _require_dangerous_eval_api_enabled()
    try:
        guest_id = _resolve_guest_id(request)
        messages = _call_seed_sample_data(seed_sample_data_fn, db, guest_id)

        if not messages:
            return {"status": "ok", "message": "Data already exists, nothing new seeded."}

        return {"status": "ok", "message": "; ".join(messages)}

    except Exception as exc:
        db.rollback()
        raise_internal_server_error("サンプルデータ投入に失敗しました。", exc=exc)


# 日本語: 評価ログ保存API / English: Persist evaluation result record
async def evaluation_log(request: Request, db: Session):
    _require_dangerous_eval_api_enabled()
    try:
        data = await request.json()
    except Exception:
        data = {}
    try:
        result = EvaluationResult(
            guest_id=_resolve_guest_id(request),
            model_name=data.get("model_name"),
            task_prompt=data.get("task_prompt"),
            agent_reply=data.get("agent_reply"),
            tool_calls=json.dumps(data.get("tool_calls", [])),
            is_success=data.get("is_success"),
            comments=data.get("comments"),
        )
        db.add(result)
        db.commit()
        return {"status": "ok"}
    except Exception as exc:
        db.rollback()
        raise_internal_server_error("評価ログの保存に失敗しました。", exc=exc)


# 日本語: 評価履歴一覧API / English: List evaluation result history
def evaluation_history(db: Session, request: Request | None = None):
    guest_id = _resolve_guest_id(request)
    results = db.exec(
        select(EvaluationResult)
        .where(EvaluationResult.guest_id == guest_id)
        .order_by(EvaluationResult.timestamp.desc())
    ).all()
    data = []
    for result in results:
        data.append(
            {
                "id": result.id,
                "timestamp": result.timestamp.isoformat(),
                "model_name": result.model_name,
                "task_prompt": result.task_prompt,
                "is_success": result.is_success,
            }
        )
    return {"history": data}
