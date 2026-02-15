"""Timeline and context services."""

from __future__ import annotations

import datetime
from typing import List

from sqlmodel import Session, select

from scheduler_agent.models import CustomTask, DailyLog, DayLog, Routine


def get_weekday_routines(db: Session, weekday_int: int) -> List[Routine]:
    all_routines = db.exec(select(Routine)).all()
    matched = []
    for routine in all_routines:
        if str(weekday_int) in (routine.days or "").split(","):
            matched.append(routine)
    return matched


def _get_timeline_data(db: Session, date_obj: datetime.date):
    routines = get_weekday_routines(db, date_obj.weekday())
    custom_tasks = db.exec(select(CustomTask).where(CustomTask.date == date_obj)).all()

    timeline_items = []
    total_items = 0
    completed_items = 0

    for routine in routines:
        for step in routine.steps:
            log = db.exec(
                select(DailyLog).where(DailyLog.date == date_obj, DailyLog.step_id == step.id)
            ).first()
            timeline_items.append(
                {
                    "type": "routine",
                    "routine": routine,
                    "step": step,
                    "log": log,
                    "time": step.time,
                    "id": step.id,
                }
            )
            total_items += 1
            if log and log.done:
                completed_items += 1

    for task in custom_tasks:
        timeline_items.append(
            {
                "type": "custom",
                "routine": {"name": "Personal"},
                "step": {"name": task.name, "category": "Custom", "id": task.id},
                "log": {"done": task.done, "memo": task.memo},
                "time": task.time,
                "id": task.id,
                "real_obj": task,
            }
        )
        total_items += 1
        if task.done:
            completed_items += 1

    timeline_items.sort(key=lambda item: item["time"])

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
        date_value = today - datetime.timedelta(days=i)
        day_log = db.exec(select(DayLog).where(DayLog.date == date_value)).first()
        if day_log and day_log.content:
            recent_day_logs.append(f"Date: {date_value.isoformat()} | Content: {day_log.content}")

    routine_lines = []
    for routine in routines:
        days_label = routine.days or ""
        steps = (
            ", ".join(
                f"[{step.id}] {step.time} {step.name} ({step.category})"
                for step in sorted(routine.steps, key=lambda item: item.time)
            )
            or "no steps"
        )
        routine_lines.append(f"- Routine {routine.id}: {routine.name} | days={days_label} | {steps}")

    custom_lines = []
    for task in sorted(custom_tasks, key=lambda item: item.time):
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


__all__ = [
    "get_weekday_routines",
    "_get_timeline_data",
    "_build_scheduler_context",
]
