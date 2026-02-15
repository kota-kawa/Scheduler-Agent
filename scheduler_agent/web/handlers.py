"""HTTP handler implementations used by compatibility wrappers."""

from __future__ import annotations

import calendar
import datetime
import json
from typing import Callable, Dict, List

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import delete as sa_delete
from sqlmodel import Session, select

from model_selection import apply_model_selection, current_available_models, update_override
from scheduler_agent.models import (
    ChatHistory,
    CustomTask,
    DailyLog,
    DayLog,
    EvaluationResult,
    Routine,
    Step,
)


def api_flash(
    request: Request,
    *,
    pop_flashed_messages_fn,
):
    return {"messages": pop_flashed_messages_fn(request)}


def api_calendar(
    request: Request,
    db: Session,
    *,
    get_weekday_routines_fn,
):
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
            routines = get_weekday_routines_fn(db, weekday)
            total_steps = sum(len(r.steps) for r in routines)

            logs = db.exec(select(DailyLog).where(DailyLog.date == day)).all()
            completed_count = sum(1 for log in logs if log.done)

            custom_tasks = db.exec(select(CustomTask).where(CustomTask.date == day)).all()
            total_steps += len(custom_tasks)
            completed_count += sum(1 for task in custom_tasks if task.done)

            day_log = db.exec(select(DayLog).where(DayLog.date == day)).first()
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


def index(request: Request, *, template_response_fn):
    return template_response_fn(request, "spa.html", {"page_id": "index"})


def agent_result(request: Request, *, template_response_fn):
    return template_response_fn(request, "spa.html", {"page_id": "agent-result"})


async def agent_day_view(
    request: Request,
    date_str: str,
    db: Session,
    *,
    get_weekday_routines_fn,
    flash_fn,
    template_response_fn,
):
    try:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse(url=str(request.url_for("agent_result")), status_code=303)

    if request.method == "POST":
        form = await request.form()

        if "add_custom_task" in form:
            name = form.get("custom_name")
            time_value = form.get("custom_time")
            if name:
                task = CustomTask(date=date_obj, name=name, time=time_value)
                db.add(task)
                db.commit()
                flash_fn(request, "カスタムタスクを追加しました。")
            return RedirectResponse(
                url=str(request.url_for("agent_day_view", date_str=date_str)), status_code=303
            )

        if "save_log" in form:
            content = form.get("day_log_content")
            day_log = db.exec(select(DayLog).where(DayLog.date == date_obj)).first()
            if not day_log:
                day_log = DayLog(date=date_obj)
                db.add(day_log)
            day_log.content = content
            db.commit()
            flash_fn(request, "日報を保存しました。")
            return RedirectResponse(
                url=str(request.url_for("agent_day_view", date_str=date_str)), status_code=303
            )

        if "delete_custom_task" in form:
            task_id = form.get("delete_custom_task")
            task = db.get(CustomTask, int(task_id)) if task_id else None
            if task:
                db.delete(task)
                db.commit()
                flash_fn(request, "タスクを削除しました。")
            return RedirectResponse(
                url=str(request.url_for("agent_day_view", date_str=date_str)), status_code=303
            )

        routines = get_weekday_routines_fn(db, date_obj.weekday())
        all_steps = []
        for routine in routines:
            all_steps.extend(routine.steps)

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
        flash_fn(request, "進捗を保存しました。")
        return RedirectResponse(
            url=str(request.url_for("agent_day_view", date_str=date_str)), status_code=303
        )

    return template_response_fn(request, "spa.html", {"page_id": "agent-day"})


def embed_calendar(request: Request, *, template_response_fn):
    return template_response_fn(request, "spa.html", {"page_id": "embed-calendar"})


def api_day_view(
    date_str: str,
    db: Session,
    *,
    get_timeline_data_fn,
):
    try:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    timeline_items, completion_rate = get_timeline_data_fn(db, date_obj)
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
        "weekday": date_obj.weekday(),
        "day_name": date_obj.strftime("%A"),
        "date_display": date_obj.strftime("%Y.%m.%d"),
        "timeline_items": serialized_timeline_items,
        "completion_rate": completion_rate,
        "day_log_content": day_log.content if day_log else None,
    }


async def day_view(
    request: Request,
    date_str: str,
    db: Session,
    *,
    get_weekday_routines_fn,
    flash_fn,
    template_response_fn,
):
    try:
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse(url=str(request.url_for("index")), status_code=303)

    if request.method == "POST":
        form = await request.form()

        if "add_custom_task" in form:
            name = form.get("custom_name")
            time_value = form.get("custom_time")
            if name:
                task = CustomTask(date=date_obj, name=name, time=time_value)
                db.add(task)
                db.commit()
                flash_fn(request, "カスタムタスクを追加しました。")
            return RedirectResponse(
                url=str(request.url_for("day_view", date_str=date_str)), status_code=303
            )

        if "save_log" in form:
            content = form.get("day_log_content")
            day_log = db.exec(select(DayLog).where(DayLog.date == date_obj)).first()
            if not day_log:
                day_log = DayLog(date=date_obj)
                db.add(day_log)
            day_log.content = content
            db.commit()
            flash_fn(request, "日報を保存しました。")
            return RedirectResponse(
                url=str(request.url_for("day_view", date_str=date_str)), status_code=303
            )

        if "delete_custom_task" in form:
            task_id = form.get("delete_custom_task")
            task = db.get(CustomTask, int(task_id)) if task_id else None
            if task:
                db.delete(task)
                db.commit()
                flash_fn(request, "タスクを削除しました。")
            return RedirectResponse(
                url=str(request.url_for("day_view", date_str=date_str)), status_code=303
            )

        routines = get_weekday_routines_fn(db, date_obj.weekday())
        all_steps = []
        for routine in routines:
            all_steps.extend(routine.steps)

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
        flash_fn(request, "進捗を保存しました。")
        return RedirectResponse(
            url=str(request.url_for("day_view", date_str=date_str)), status_code=303
        )

    return template_response_fn(request, "spa.html", {"page_id": "day"})


def api_routines_by_day(weekday: int, db: Session, *, get_weekday_routines_fn):
    routines = get_weekday_routines_fn(db, weekday)
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


def api_routines(db: Session):
    routines = db.exec(select(Routine)).all()
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


def routines_list(request: Request, *, template_response_fn):
    return template_response_fn(request, "spa.html", {"page_id": "routines"})


async def add_routine(request: Request, db: Session):
    form = await request.form()
    name = form.get("name")
    days = ",".join(form.getlist("days"))
    desc = form.get("description")
    if name:
        routine = Routine(name=name, days=days, description=desc)
        db.add(routine)
        db.commit()
    return RedirectResponse(url=str(request.url_for("routines_list")), status_code=303)


def delete_routine(request: Request, id: int, db: Session):
    routine = db.get(Routine, id)
    if not routine:
        raise HTTPException(status_code=404, detail="Routine not found")
    db.delete(routine)
    db.commit()
    return RedirectResponse(url=str(request.url_for("routines_list")), status_code=303)


async def add_step(request: Request, id: int, db: Session):
    form = await request.form()
    routine = db.get(Routine, id)
    if not routine:
        raise HTTPException(status_code=404, detail="Routine not found")
    name = form.get("name")
    time_value = form.get("time")
    category = form.get("category")
    if name:
        step = Step(routine_id=routine.id, name=name, time=time_value, category=category)
        db.add(step)
        db.commit()
    return RedirectResponse(url=str(request.url_for("routines_list")), status_code=303)


def delete_step(request: Request, id: int, db: Session):
    step = db.get(Step, id)
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    db.delete(step)
    db.commit()
    return RedirectResponse(url=str(request.url_for("routines_list")), status_code=303)


def list_models(*, apply_model_selection_fn=apply_model_selection, current_available_models_fn=current_available_models):
    provider, model, base_url, _ = apply_model_selection_fn("scheduler")
    return {
        "models": current_available_models_fn(),
        "current": {"provider": provider, "model": model, "base_url": base_url},
    }


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
        raise HTTPException(status_code=500, detail=f"モデル設定の更新に失敗しました: {exc}")
    return {"status": "ok", "applied": {"provider": provider, "model": model, "base_url": base_url}}


async def manage_chat_history(
    request: Request,
    db: Session,
    *,
    extract_execution_trace_fn,
    delete_fn=sa_delete,
):
    if request.method == "DELETE":
        try:
            db.exec(delete_fn(ChatHistory))
            db.commit()
            return {"status": "cleared"}
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=str(exc))

    history = db.exec(select(ChatHistory).order_by(ChatHistory.timestamp)).all()
    serialized_history = []
    for item in history:
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

    return process_chat_request_fn(db, recent_messages)


def evaluation_page(request: Request, *, template_response_fn):
    return template_response_fn(request, "spa.html", {"page_id": "evaluation"})


async def evaluation_chat(
    request: Request,
    db: Session,
    *,
    run_scheduler_multi_step_fn,
    build_final_reply_fn,
):
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
    execution = run_scheduler_multi_step_fn(db, formatted_messages, today)
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


def evaluation_reset(db: Session, *, delete_fn=sa_delete):
    try:
        db.exec(delete_fn(DailyLog))
        db.exec(delete_fn(CustomTask))
        db.exec(delete_fn(Step))
        db.exec(delete_fn(Routine))
        db.exec(delete_fn(DayLog))
        db.commit()
        return {"status": "ok", "message": "Scheduler data cleared."}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))


async def evaluation_seed(request: Request, db: Session, *, seed_evaluation_data_fn):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    date_str = payload.get("date") or request.query_params.get("date")
    if date_str:
        target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        target_date = datetime.date.today()

    messages = seed_evaluation_data_fn(db, target_date, target_date)
    return {"status": "ok", "message": "; ".join(messages)}


async def evaluation_seed_period(request: Request, db: Session, *, seed_evaluation_data_fn):
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

    messages = seed_evaluation_data_fn(db, start_date, end_date)
    return {"status": "ok", "message": "; ".join(messages)}


def add_sample_data(db: Session, *, seed_sample_data_fn):
    try:
        messages = seed_sample_data_fn(db)

        if not messages:
            return {"status": "ok", "message": "Data already exists, nothing new seeded."}

        return {"status": "ok", "message": "; ".join(messages)}

    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(exc))


async def evaluation_log(request: Request, db: Session):
    try:
        data = await request.json()
    except Exception:
        data = {}
    try:
        result = EvaluationResult(
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
        raise HTTPException(status_code=500, detail=str(exc))


def evaluation_history(db: Session):
    results = db.exec(
        select(EvaluationResult).order_by(EvaluationResult.timestamp.desc())
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
