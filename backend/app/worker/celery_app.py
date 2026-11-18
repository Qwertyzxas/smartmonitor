from __future__ import annotations

from datetime import timedelta

from typing import Any

from celery import Celery
from celery.schedules import crontab
from celery.signals import beat_init

from app.core.config import settings

celery_app = Celery("smartmonitor", broker=settings.redis_url, backend=settings.redis_url,
                    include=["app.worker.tasks"])

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    result_expires=3600,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_routes={"smartmonitor.run_system_tests": {"queue": "qa"}},
    beat_schedule={
        "dispatch-due-checks": {
            "task": "smartmonitor.dispatch_due_checks",
            "schedule": timedelta(seconds=settings.dispatch_interval_seconds),
        },
        "system-tests": {
            "task": "smartmonitor.run_system_tests",
            "schedule": timedelta(minutes=settings.system_tests_interval_minutes),
            "args": ["scheduled"],
        },
        "daily-telegram-report": {
            "task": "smartmonitor.send_report",
            "schedule": crontab(hour=settings.report_hour_utc, minute=0),
        },
        "retry-unanalysed-incidents": {
            "task": "smartmonitor.retry_unanalysed",
            "schedule": timedelta(minutes=2),
        },
    },
)


@beat_init.connect
def _run_tests_on_start(sender: Any = None, **_: Any) -> None:
    try:
        celery_app.send_task("smartmonitor.run_system_tests", args=["startup"], countdown=40)
    except Exception:
        pass
