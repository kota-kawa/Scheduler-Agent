"""Action application service for scheduler tool calls."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List

from sqlmodel import Session, select

from scheduler_agent.models import CustomTask, DailyLog, DayLog, Routine, Step
from scheduler_agent.services.schedule_parser_service import (
    _bool_from_value,
    _is_relative_datetime_text,
    _normalize_hhmm,
    _parse_date,
    _resolve_schedule_expression,
)
from scheduler_agent.services.timeline_service import get_weekday_routines

READ_ONLY_ACTION_TYPES = {
    "resolve_schedule_expression",
    "get_day_log",
    "list_tasks_in_period",
    "get_daily_summary",
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

            if action_type == "resolve_schedule_expression":
                expression = action.get("expression")
                if not isinstance(expression, str) or not expression.strip():
                    errors.append("resolve_schedule_expression: expression が指定されていません。")
                    continue
                base_date_value = _parse_date(action.get("base_date"), default_date)
                fallback_base_time = datetime.datetime.now().strftime("%H:%M")
                base_time_value = _normalize_hhmm(action.get("base_time"), fallback_base_time)
                default_time_value = _normalize_hhmm(
                    action.get("default_time"),
                    base_time_value,
                )
                calc = _resolve_schedule_expression(
                    expression=expression,
                    base_date=base_date_value,
                    base_time=base_time_value,
                    default_time=default_time_value,
                )
                if not calc.get("ok"):
                    errors.append(
                        "resolve_schedule_expression: "
                        + str(calc.get("error") or "日時の計算に失敗しました。")
                    )
                    continue
                period_text = ""
                if calc.get("period_start") and calc.get("period_end"):
                    period_text = (
                        f" period_start={calc.get('period_start')}"
                        f" period_end={calc.get('period_end')}"
                    )
                results.append(
                    "計算結果: "
                    f"expression={expression.strip()} "
                    f"date={calc.get('date')} "
                    f"time={calc.get('time')} "
                    f"datetime={calc.get('datetime')} "
                    f"source={calc.get('source')}"
                    f"{period_text}"
                )
                continue

            if action_type == "create_custom_task":
                name = action.get("name")
                if not isinstance(name, str) or not name.strip():
                    errors.append("create_custom_task: name が指定されていません。")
                    continue
                raw_date_value = action.get("date")
                if _is_relative_datetime_text(raw_date_value):
                    errors.append(
                        "create_custom_task: date に相対表現が含まれています。"
                        " resolve_schedule_expression で先に絶対日時へ変換してください。"
                    )
                    continue
                raw_time_value = action.get("time")
                if _is_relative_datetime_text(raw_time_value):
                    errors.append(
                        "create_custom_task: time に相対表現が含まれています。"
                        " resolve_schedule_expression で先に絶対日時へ変換してください。"
                    )
                    continue
                date_value = _parse_date(raw_date_value, default_date)
                time_value = raw_time_value if isinstance(raw_time_value, str) else "00:00"
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
                raw_date_value = action.get("date")
                if _is_relative_datetime_text(raw_date_value):
                    errors.append(
                        "toggle_step: date に相対表現が含まれています。"
                        " resolve_schedule_expression で先に絶対日付へ変換してください。"
                    )
                    continue
                date_value = _parse_date(raw_date_value, default_date)
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
                task_obj.time = str(new_time).strip()
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
                task_obj.name = str(new_name).strip()
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
                task_obj.memo = str(new_memo).strip()
                results.append(f"カスタムタスク「{task_obj.name}」のメモを更新しました。")
                modified_ids.append(f"item_custom_{task_obj.id}")
                dirty = True
                continue

            if action_type == "update_log":
                content = action.get("content")
                if not isinstance(content, str) or not content.strip():
                    errors.append("update_log: content が指定されていません。")
                    continue
                raw_date_value = action.get("date")
                if _is_relative_datetime_text(raw_date_value):
                    errors.append(
                        "update_log: date に相対表現が含まれています。"
                        " resolve_schedule_expression で先に絶対日付へ変換してください。"
                    )
                    continue
                date_value = _parse_date(raw_date_value, default_date)
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
                raw_date_value = action.get("date")
                if _is_relative_datetime_text(raw_date_value):
                    errors.append(
                        "append_day_log: date に相対表現が含まれています。"
                        " resolve_schedule_expression で先に絶対日付へ変換してください。"
                    )
                    continue
                date_value = _parse_date(raw_date_value, default_date)
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
                raw_date_value = action.get("date")
                if _is_relative_datetime_text(raw_date_value):
                    errors.append(
                        "get_day_log: date に相対表現が含まれています。"
                        " resolve_schedule_expression で先に絶対日付へ変換してください。"
                    )
                    continue
                date_value = _parse_date(raw_date_value, default_date)
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
                routine = Routine(name=name, days=days, description=desc)
                db.add(routine)
                db.flush()
                results.append(f"ルーチン「{name}」(ID: {routine.id}) を追加しました。")
                dirty = True
                continue

            if action_type == "delete_routine":
                rid = action.get("routine_id")
                routine = db.get(Routine, int(rid)) if rid else None
                if routine:
                    db.delete(routine)
                    results.append(f"ルーチン「{routine.name}」を削除しました。")
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
                routine_obj.days = str(new_days).strip()
                results.append(f"ルーチン「{routine_obj.name}」の曜日を {routine_obj.days} に更新しました。")
                dirty = True
                continue

            if action_type == "add_step":
                rid = action.get("routine_id")
                name = action.get("name")
                if not rid or not name:
                    errors.append("add_step: routine_id and name required")
                    continue
                step = Step(
                    routine_id=int(rid),
                    name=name,
                    time=action.get("time", "00:00"),
                    category=action.get("category", "Other"),
                )
                db.add(step)
                db.flush()
                results.append(f"ルーチン(ID:{rid})にステップ「{name}」(ID: {step.id}) を追加しました。")
                modified_ids.append(f"item_routine_{step.id}")
                dirty = True
                continue

            if action_type == "delete_step":
                sid = action.get("step_id")
                step = db.get(Step, int(sid)) if sid else None
                if step:
                    db.delete(step)
                    results.append(f"ステップ「{step.name}」を削除しました。")
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
                step_obj.time = str(new_time).strip()
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
                step_obj.name = str(new_name).strip()
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
                step_obj.memo = str(new_memo).strip()
                results.append(f"ステップ「{step_obj.name}」のメモを更新しました。")
                modified_ids.append(f"item_routine_{step_obj.id}")
                dirty = True
                continue

            if action_type == "list_tasks_in_period":
                raw_start_date = action.get("start_date")
                raw_end_date = action.get("end_date")
                if _is_relative_datetime_text(raw_start_date) or _is_relative_datetime_text(raw_end_date):
                    errors.append(
                        "list_tasks_in_period: 相対日付が含まれています。"
                        " resolve_schedule_expression で先に絶対日付へ変換してください。"
                    )
                    continue
                start_date = _parse_date(raw_start_date, default_date)
                end_date = _parse_date(raw_end_date, default_date)

                if start_date > end_date:
                    errors.append("list_tasks_in_period: 開始日が終了日より後です。")
                    continue

                tasks_info = []

                custom_tasks = db.exec(
                    select(CustomTask)
                    .where(CustomTask.date.between(start_date, end_date))
                    .order_by(CustomTask.date, CustomTask.time)
                ).all()
                for custom_task in custom_tasks:
                    tasks_info.append(
                        f"カスタムタスク [{custom_task.id}]: {custom_task.date.isoformat()} {custom_task.time} - {custom_task.name} (完了: {custom_task.done}) (メモ: {custom_task.memo if custom_task.memo else 'なし'})"
                    )

                current_date = start_date
                while current_date <= end_date:
                    routines_for_day = get_weekday_routines(db, current_date.weekday())
                    for routine in routines_for_day:
                        for step in routine.steps:
                            log = db.exec(
                                select(DailyLog).where(
                                    DailyLog.date == current_date, DailyLog.step_id == step.id
                                )
                            ).first()
                            status = "完了" if log and log.done else "未完了"
                            memo = log.memo if log and log.memo else (step.memo if step.memo else "なし")
                            tasks_info.append(
                                f"ルーチンステップ [{step.id}]: {current_date.isoformat()} {step.time} - {routine.name} - {step.name} (完了: {status}) (メモ: {memo})"
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
                raw_date_value = action.get("date")
                if _is_relative_datetime_text(raw_date_value):
                    errors.append(
                        "get_daily_summary: date に相対表現が含まれています。"
                        " resolve_schedule_expression で先に絶対日付へ変換してください。"
                    )
                    continue
                target_date = _parse_date(raw_date_value, default_date)

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
                    for custom_task in custom_tasks:
                        status = "完了" if custom_task.done else "未完了"
                        summary_parts.append(
                            f"- {custom_task.time} {custom_task.name} ({status}) (メモ: {custom_task.memo if custom_task.memo else 'なし'})"
                        )
                else:
                    summary_parts.append("カスタムタスク: なし")

                routines_for_day = get_weekday_routines(db, target_date.weekday())
                if routines_for_day:
                    summary_parts.append("ルーチンステップ:")
                    for routine in routines_for_day:
                        for step in routine.steps:
                            log = db.exec(
                                select(DailyLog).where(
                                    DailyLog.date == target_date, DailyLog.step_id == step.id
                                )
                            ).first()
                            status = "完了" if log and log.done else "未完了"
                            memo = log.memo if log and log.memo else (step.memo if step.memo else "なし")
                            summary_parts.append(
                                f"- {step.time} {routine.name} - {step.name} ({status}) (メモ: {memo})"
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


__all__ = ["READ_ONLY_ACTION_TYPES", "_apply_actions"]
