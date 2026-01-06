import datetime
import importlib
import os
import sys

import pytest
from sqlmodel import select


def _load_app():
    db_url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        pytest.skip("Set TEST_DATABASE_URL or DATABASE_URL to run PostgreSQL-backed tests.")
    os.environ["DATABASE_URL"] = db_url
    os.environ["SESSION_SECRET"] = "test-secret"
    if "app" in sys.modules:
        del sys.modules["app"]
    app_module = importlib.import_module("app")
    app_module._init_db()
    return app_module


@pytest.fixture()
def app_module():
    return _load_app()


def test_apply_actions_custom_task_flow(app_module):
    db = app_module.create_session()
    today = datetime.date.today()
    try:
        actions = [
            {"type": "create_custom_task", "name": "買い物", "date": today.isoformat(), "time": "09:00"},
        ]
        results, errors, modified = app_module._apply_actions(db, actions, today)
        assert not errors
        assert any("買い物" in item for item in results)
        assert modified

        task = db.exec(
            select(app_module.CustomTask).where(app_module.CustomTask.name == "買い物")
        ).first()
        assert task is not None

        actions = [
            {"type": "toggle_custom_task", "task_id": task.id, "done": True, "memo": "近所"},
            {"type": "rename_custom_task", "task_id": task.id, "new_name": "週末の買い物"},
            {"type": "update_custom_task_time", "task_id": task.id, "new_time": "10:30"},
        ]
        results, errors, _ = app_module._apply_actions(db, actions, today)
        assert not errors
        task = db.exec(
            select(app_module.CustomTask).where(app_module.CustomTask.id == task.id)
        ).first()
        assert task.done is True
        assert task.memo == "近所"
        assert task.name == "週末の買い物"
        assert task.time == "10:30"
    finally:
        db.close()


def test_apply_actions_routine_step_flow(app_module):
    db = app_module.create_session()
    today = datetime.date.today()
    try:
        actions = [{"type": "add_routine", "name": "Morning", "days": "0,2"}]
        app_module._apply_actions(db, actions, today)
        routine = db.exec(
            select(app_module.Routine).where(app_module.Routine.name == "Morning")
        ).first()
        assert routine is not None

        actions = [
            {"type": "add_step", "routine_id": routine.id, "name": "Coffee", "time": "07:30"},
            {"type": "update_routine_days", "routine_id": routine.id, "new_days": "0,1,2"},
        ]
        app_module._apply_actions(db, actions, today)
        routine = db.exec(
            select(app_module.Routine).where(app_module.Routine.id == routine.id)
        ).first()
        assert routine.days == "0,1,2"

        step = db.exec(
            select(app_module.Step).where(
                app_module.Step.routine_id == routine.id, app_module.Step.name == "Coffee"
            )
        ).first()
        assert step is not None

        actions = [
            {"type": "toggle_step", "step_id": step.id, "date": today.isoformat(), "done": True},
            {"type": "update_step_time", "step_id": step.id, "new_time": "08:00"},
            {"type": "rename_step", "step_id": step.id, "new_name": "Espresso"},
            {"type": "update_step_memo", "step_id": step.id, "new_memo": "豆を挽く"},
        ]
        app_module._apply_actions(db, actions, today)
        step = db.exec(select(app_module.Step).where(app_module.Step.id == step.id)).first()
        assert step.time == "08:00"
        assert step.name == "Espresso"
        assert step.memo == "豆を挽く"

        log = db.exec(
            select(app_module.DailyLog).where(
                app_module.DailyLog.step_id == step.id, app_module.DailyLog.date == today
            )
        ).first()
        assert log and log.done is True

        actions = [
            {"type": "delete_step", "step_id": step.id},
            {"type": "delete_routine", "routine_id": routine.id},
        ]
        app_module._apply_actions(db, actions, today)
        assert (
            db.exec(select(app_module.Step).where(app_module.Step.id == step.id)).first()
            is None
        )
        assert (
            db.exec(select(app_module.Routine).where(app_module.Routine.id == routine.id)).first()
            is None
        )
    finally:
        db.close()


def test_timeline_and_summary_helpers(app_module):
    db = app_module.create_session()
    today = datetime.date.today()
    try:
        routine = app_module.Routine(name="Daily", days="0,1,2,3,4,5,6")
        db.add(routine)
        db.flush()
        step = app_module.Step(routine_id=routine.id, name="Stretch", time="06:30")
        db.add(step)
        db.flush()
        db.add(app_module.CustomTask(date=today, name="Meeting", time="10:00", done=True))
        db.add(app_module.DailyLog(date=today, step_id=step.id, done=False))
        db.commit()

        items, rate = app_module._get_timeline_data(db, today)
        assert len(items) == 2
        assert rate == 50

        actions = [
            {"type": "get_daily_summary", "date": today.isoformat()},
            {
                "type": "list_tasks_in_period",
                "start_date": today.isoformat(),
                "end_date": today.isoformat(),
            },
        ]
        results, errors, _ = app_module._apply_actions(db, actions, today)
        assert not errors
        assert any("活動概要" in item for item in results)
        assert any("タスク" in item for item in results)
    finally:
        db.close()


def test_build_scheduler_context(app_module):
    db = app_module.create_session()
    today = datetime.date.today()
    try:
        routine = app_module.Routine(name="Daily", days="0,1,2,3,4,5,6")
        db.add(routine)
        db.flush()
        step = app_module.Step(routine_id=routine.id, name="Stretch", time="06:30")
        db.add(step)
        db.add(app_module.CustomTask(date=today, name="Meeting", time="10:00"))
        db.add(app_module.DayLog(date=today, content="progress"))
        db.commit()

        context = app_module._build_scheduler_context(db, today)
        assert "today_date" in context
        assert "Routine" in context
        assert "CustomTask" in context
        assert "recent_day_logs" in context
    finally:
        db.close()


def test_create_session_provides_sqlmodel_session(app_module):
    db = app_module.create_session()
    try:
        assert isinstance(db, app_module.Session)
    finally:
        db.close()
