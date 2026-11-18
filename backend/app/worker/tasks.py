"""Celery tasks."""
from __future__ import annotations

from datetime import timedelta

from celery.signals import worker_process_init
from loguru import logger
from sqlalchemy import select

from app.core import cache
from app.core.database import SessionLocal
from app.core.logging import setup_logging
from app.models import Incident, IncidentStatus, as_aware, utcnow
from app.repositories import services as services_repo
from app.services import ai_agent, monitor, notifications, qa_runner
from app.worker.celery_app import celery_app

setup_logging("worker")


@worker_process_init.connect
def _init_worker(**_: object) -> None:
    from app.core.database import engine

    engine.dispose()  # fresh connection pool per forked worker process


@celery_app.task(name="smartmonitor.dispatch_due_checks")
def dispatch_due_checks() -> int:
    """Enqueue a check for every active service whose interval has elapsed."""
    now = utcnow()
    dispatched = 0
    with SessionLocal() as db:
        for service in services_repo.list_active(db):
            last = as_aware(service.last_checked_at)
            if last is not None and last + timedelta(seconds=service.interval_seconds) > now:
                continue
            # dedupe: do not enqueue again while a check for this service is pending
            if not cache.acquire_lock(f"lock:dispatch:{service.id}", ttl=max(service.interval_seconds - 1, 5)):
                continue
            check_service.delay(service.id)
            dispatched += 1
    if dispatched:
        logger.debug("Dispatched {} checks", dispatched)
    return dispatched


@celery_app.task(name="smartmonitor.check_service")
def check_service(service_id: int) -> dict[str, object] | None:
    with SessionLocal() as db:
        service = services_repo.get(db, service_id)
        if service is None or not service.is_active:
            return None
        outcome = monitor.run_check(db, service)
        return {"check_id": outcome.check.id, "status": outcome.check.status,
                "incident_opened": outcome.incident_opened_id}


@celery_app.task(name="smartmonitor.analyze_incident", bind=True, max_retries=2, default_retry_delay=30)
def analyze_incident(self, incident_id: int) -> int | None:  # type: ignore[no-untyped-def]
    try:
        with SessionLocal() as db:
            action = ai_agent.analyze_incident(db, incident_id)
            return action.id if action else None
    except Exception as exc:  # noqa: BLE001
        raise self.retry(exc=exc)


@celery_app.task(name="smartmonitor.retry_unanalysed")
def retry_unanalysed() -> int:
    """Safety net: analyse open incidents that have no agent action yet (e.g. worker was down)."""
    count = 0
    with SessionLocal() as db:
        incidents = db.scalars(select(Incident).where(Incident.status == IncidentStatus.open.value)).all()
        for incident in incidents:
            started = as_aware(incident.started_at)
            if not incident.actions and started and utcnow() - started > timedelta(minutes=1):
                analyze_incident.delay(incident.id)
                count += 1
    return count


@celery_app.task(name="smartmonitor.run_system_tests")
def run_system_tests(trigger: str = "scheduled") -> int | None:
    return qa_runner.run_system_tests(trigger)


@celery_app.task(name="smartmonitor.send_report")
def send_report() -> bool:
    return notifications.send_report()
