#!/usr/bin/env python3
"""Migrate Scheduler-Agent data from SQLite to PostgreSQL."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select


def _load_models():
    # Importing app defines the SQLModel models.
    import app as app_module  # noqa: WPS433

    return app_module


def _fetch_all(session: Session, model: type[SQLModel]) -> list[SQLModel]:
    return list(session.exec(select(model)).all())


def _clone_row(model: type[SQLModel], row: SQLModel) -> SQLModel:
    data = {col.name: getattr(row, col.name) for col in model.__table__.columns}
    return model(**data)


def _count_rows(session: Session, models: Iterable[type[SQLModel]]) -> int:
    total = 0
    for model in models:
        count = session.exec(text(f"SELECT COUNT(*) FROM {model.__tablename__}")).one()
        total += int(count[0])
    return total


def _truncate_tables(session: Session, models: Iterable[type[SQLModel]]) -> None:
    for model in models:
        session.exec(text(f"TRUNCATE TABLE {model.__tablename__} CASCADE"))


def _reset_sequences(session: Session, models: Iterable[type[SQLModel]]) -> None:
    for model in models:
        if "id" not in model.__table__.columns:
            continue
        table = model.__tablename__
        session.exec(
            text(
                "SELECT setval(pg_get_serial_sequence(:table, 'id'), "
                "COALESCE((SELECT MAX(id) FROM " + table + "), 1), true)"
            ),
            {"table": table},
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate SQLite data to PostgreSQL")
    parser.add_argument(
        "--sqlite-path",
        default=os.path.join(os.path.dirname(__file__), "..", "instance", "scheduler.db"),
        help="Path to SQLite database file",
    )
    parser.add_argument(
        "--postgres-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="Target PostgreSQL DATABASE_URL",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Truncate target tables before import",
    )

    args = parser.parse_args()
    sqlite_path = os.path.abspath(args.sqlite_path)
    postgres_url = args.postgres_url

    if not os.path.exists(sqlite_path):
        print(f"SQLite database not found: {sqlite_path}", file=sys.stderr)
        return 1

    if not postgres_url:
        print("DATABASE_URL is required for PostgreSQL target.", file=sys.stderr)
        return 1

    if postgres_url.startswith("postgres://"):
        postgres_url = postgres_url.replace("postgres://", "postgresql+psycopg2://", 1)

    if not postgres_url.startswith("postgresql"):
        print("Target DATABASE_URL must be PostgreSQL.", file=sys.stderr)
        return 1

    app_module = _load_models()

    sqlite_url = f"sqlite:///{sqlite_path}"
    sqlite_engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
    pg_engine = create_engine(postgres_url)

    SQLModel.metadata.create_all(pg_engine)

    models = [
        app_module.Routine,
        app_module.Step,
        app_module.DailyLog,
        app_module.CustomTask,
        app_module.DayLog,
        app_module.ChatHistory,
        app_module.EvaluationResult,
    ]

    with Session(sqlite_engine) as src_session, Session(pg_engine) as dst_session:
        existing_rows = _count_rows(dst_session, models)
        if existing_rows > 0 and not args.force:
            print(
                "Target database already has data. Use --force to truncate before import.",
                file=sys.stderr,
            )
            return 1

        if args.force:
            _truncate_tables(dst_session, reversed(models))

        for model in models:
            rows = _fetch_all(src_session, model)
            for row in rows:
                dst_session.add(_clone_row(model, row))
            dst_session.commit()

        _reset_sequences(dst_session, models)

    print("Migration completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
