"""Guest-scoped data utilities."""

from __future__ import annotations

import datetime
import threading
import time

from sqlmodel import Session, delete, select

from scheduler_agent.core.config import guest_data_cleanup_interval_seconds, guest_data_ttl_hours
from scheduler_agent.models import ChatHistory, CustomTask, DailyLog, DayLog, EvaluationResult, Routine, Step

_cleanup_lock = threading.Lock()
_last_cleanup_monotonic = 0.0


def _cleanup_cutoff() -> datetime.datetime:
    return datetime.datetime.now() - datetime.timedelta(hours=guest_data_ttl_hours())


def _cleanup_expired_guest_data(db: Session) -> None:
    cutoff = _cleanup_cutoff()

    stale_step_ids = db.exec(
        select(Step.id).where(Step.guest_id != "default", Step.created_at < cutoff)
    ).all()
    if stale_step_ids:
        db.exec(delete(DailyLog).where(DailyLog.step_id.in_(stale_step_ids)))

    db.exec(delete(DailyLog).where(DailyLog.guest_id != "default", DailyLog.created_at < cutoff))
    db.exec(delete(ChatHistory).where(ChatHistory.guest_id != "default", ChatHistory.created_at < cutoff))
    db.exec(delete(EvaluationResult).where(EvaluationResult.guest_id != "default", EvaluationResult.created_at < cutoff))
    db.exec(delete(CustomTask).where(CustomTask.guest_id != "default", CustomTask.created_at < cutoff))
    db.exec(delete(DayLog).where(DayLog.guest_id != "default", DayLog.created_at < cutoff))
    db.exec(delete(Step).where(Step.guest_id != "default", Step.created_at < cutoff))
    db.exec(delete(Routine).where(Routine.guest_id != "default", Routine.created_at < cutoff))
    db.commit()


def cleanup_expired_guest_data_if_due(db: Session) -> None:
    global _last_cleanup_monotonic

    interval = guest_data_cleanup_interval_seconds()
    now = time.monotonic()
    if now - _last_cleanup_monotonic < interval:
        return

    with _cleanup_lock:
        now_locked = time.monotonic()
        if now_locked - _last_cleanup_monotonic < interval:
            return
        _cleanup_expired_guest_data(db)
        _last_cleanup_monotonic = now_locked


__all__ = ["cleanup_expired_guest_data_if_due"]
