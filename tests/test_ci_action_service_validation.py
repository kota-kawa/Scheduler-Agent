import datetime

from sqlalchemy import create_engine
from sqlmodel import SQLModel, Session, select

from scheduler_agent.models import CustomTask
from scheduler_agent.services.action_service import _apply_actions


def _session_factory() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine, tables=[CustomTask.__table__])
    return Session(engine)


def test_apply_actions_rejects_non_whitelisted_action_type():
    db = _session_factory()
    today = datetime.date(2026, 3, 25)
    try:
        actions = [
            {"type": "drop_all_tables", "anything": "x"},
            {"type": "create_custom_task", "name": "買い物", "date": today.isoformat()},
        ]

        results, errors, modified_ids = _apply_actions(db, actions, today)

        assert any("未知のアクション: drop_all_tables" == err for err in errors)
        assert any("買い物" in item for item in results)
        assert modified_ids
        task = db.exec(select(CustomTask).where(CustomTask.name == "買い物")).first()
        assert task is not None
    finally:
        db.close()


def test_apply_actions_rejects_invalid_type_shape():
    db = _session_factory()
    today = datetime.date(2026, 3, 25)
    try:
        actions = [{"type": {"name": "create_custom_task"}, "name": "不正"}]

        results, errors, modified_ids = _apply_actions(db, actions, today)

        assert results == []
        assert modified_ids == []
        assert errors == ["アクション type が不正です。"]
    finally:
        db.close()
