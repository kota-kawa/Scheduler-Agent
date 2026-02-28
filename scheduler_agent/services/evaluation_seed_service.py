"""Seed helpers for evaluation/sample data."""

from __future__ import annotations

import datetime

from sqlmodel import Session, delete, select

from scheduler_agent.models import CustomTask, DailyLog, DayLog, Routine, Step


def _seed_evaluation_data(db: Session, start_date: datetime.date, end_date: datetime.date):
    # 日本語: 指定期間の評価用データを毎日再生成 / English: Rebuild deterministic evaluation fixtures for each date in range
    messages = []

    routine_name = "Daily Routine"
    # 日本語: 評価用の基準ルーチンを1つ用意 / English: Ensure one baseline routine for evaluation scenarios
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
        for time_value, name, category in steps_data:
            step = Step(routine_id=daily_routine.id, name=name, time=time_value, category=category)
            db.add(step)
        messages.append(f"Seeded Routine '{routine_name}'")

    current_date = start_date
    while current_date <= end_date:
        # 日本語: 対象日の既存データを初期化してから投入 / English: Clear existing rows before seeding target date data
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
            # 日本語: 一部ステップのみ完了済みデータを作り、評価の差分を作る / English: Mark subset of steps done to create realistic mixed completion state
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


def seed_sample_data(db: Session):
    # 日本語: 手動確認用の軽量サンプルデータ投入 / English: Seed lightweight sample data for manual verification
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

        steps_data = [
            ("07:00", "Wake up", "Lifestyle"),
            ("08:00", "Breakfast", "Lifestyle"),
            ("09:00", "Check Emails", "Browser"),
        ]
        for time_value, name, category in steps_data:
            step = Step(routine_id=daily_routine.id, name=name, time=time_value, category=category)
            db.add(step)
        messages.append(f"Seeded Routine '{routine_name}'")

    task_name = "Buy Milk"
    # 日本語: 同名同日データがあれば重複作成しない / English: Skip insert when same-day task already exists
    if not db.exec(
        select(CustomTask).where(CustomTask.date == today, CustomTask.name == task_name)
    ).first():
        db.add(CustomTask(date=today, name=task_name, time="18:00", memo="Low fat"))
        messages.append(f"Seeded Task '{task_name}' for Today ({today})")

    tomorrow = today + datetime.timedelta(days=1)
    tasks_tomorrow = [
        ("13:00", "Lunch with Alice", "At the Italian place"),
        ("15:00", "Doctor Appointment", "Bring ID"),
    ]
    for time_value, name, memo in tasks_tomorrow:
        if not db.exec(
            select(CustomTask).where(CustomTask.date == tomorrow, CustomTask.name == name)
        ).first():
            db.add(CustomTask(date=tomorrow, name=name, time=time_value, memo=memo))
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
    return messages


__all__ = ["_seed_evaluation_data", "seed_sample_data"]
