import datetime
import importlib
import os
import sys
import uuid

from sqlmodel import select


def _load_app_module():
    database_url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    assert database_url, "TEST_DATABASE_URL or DATABASE_URL must be set for PostgreSQL smoke test."

    os.environ["DATABASE_URL"] = database_url
    os.environ["SESSION_SECRET"] = os.environ.get("SESSION_SECRET") or "ci-test-secret"

    if "app" in sys.modules:
        del sys.modules["app"]

    app_module = importlib.import_module("app")
    app_module._init_db()
    return app_module


def test_postgres_smoke_can_create_and_query_routine():
    app_module = _load_app_module()
    db = app_module.create_session()
    routine = None
    routine_name = f"ci-smoke-{uuid.uuid4().hex[:8]}"

    try:
        routine = app_module.Routine(name=routine_name, days="0")
        db.add(routine)
        db.commit()

        stored = db.exec(select(app_module.Routine).where(app_module.Routine.name == routine_name)).first()
        assert stored is not None

        context = app_module._build_scheduler_context(db, datetime.date.today())
        assert "today_date" in context
    finally:
        if routine is not None and routine.id is not None:
            existing = db.get(app_module.Routine, routine.id)
            if existing is not None:
                db.delete(existing)
                db.commit()
        db.close()
