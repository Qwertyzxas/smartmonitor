"""Background job submission: Celery when available, in-process thread otherwise."""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from loguru import logger

from app.core.config import settings
from app.core.database import SessionLocal


def _run_in_thread(fn: Callable[..., Any], *args: Any) -> None:
    def runner() -> None:
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            logger.exception("Background job {} failed", getattr(fn, "__name__", fn))

    threading.Thread(target=runner, daemon=True).start()


def _submit(task_name: str, args: list[Any], fallback: Callable[..., Any]) -> str:
    if not settings.celery_eager:
        try:
            from app.worker.celery_app import celery_app

            celery_app.send_task(task_name, args=args, retry=False)
            return "celery"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Celery unavailable ({}), running {} in-process", exc, task_name)
    _run_in_thread(fallback, *args)
    return "thread"


def _analyze(incident_id: int) -> None:
    from app.services import ai_agent

    with SessionLocal() as db:
        ai_agent.analyze_incident(db, incident_id)


def _tests(trigger: str) -> None:
    from app.services import qa_runner

    qa_runner.run_system_tests(trigger)


def enqueue_analysis(incident_id: int) -> str:
    return _submit("smartmonitor.analyze_incident", [incident_id], _analyze)


def enqueue_test_run(trigger: str = "manual") -> str:
    return _submit("smartmonitor.run_system_tests", [trigger], _tests)
