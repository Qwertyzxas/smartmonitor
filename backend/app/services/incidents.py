"""Incident lifecycle: open after N consecutive failed checks, resolve on recovery."""
from __future__ import annotations

from dataclasses import dataclass

from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Check, CheckStatus, Incident, IncidentStatus, Service, utcnow
from app.repositories import checks as checks_repo
from app.repositories import incidents as incidents_repo


@dataclass
class Transition:
    opened: Incident | None = None
    resolved: Incident | None = None


def process_check(db: Session, service: Service, check: Check, reason: str,
                  threshold: int | None = None) -> Transition:
    threshold = threshold or settings.incident_threshold
    open_incident = incidents_repo.get_open(db, service.id)
    failing = check.status != CheckStatus.up.value

    if failing:
        if open_incident is not None:
            open_incident.failed_checks += 1
            return Transition()
        last = checks_repo.recent(db, service.id, limit=threshold)
        if len(last) >= threshold and all(c.status != CheckStatus.up.value for c in last):
            incident = incidents_repo.add(db, Incident(
                service_id=service.id,
                status=IncidentStatus.open.value,
                started_at=last[-1].checked_at,
                reason=reason[:500],
                failed_checks=len(last),
            ))
            logger.warning("Incident #{} opened for '{}': {}", incident.id, service.name, reason)
            return Transition(opened=incident)
        return Transition()

    if open_incident is not None:
        resolve(open_incident)
        logger.info("Incident #{} resolved for '{}'", open_incident.id, service.name)
        return Transition(resolved=open_incident)
    return Transition()


def resolve(incident: Incident) -> None:
    incident.status = IncidentStatus.resolved.value
    incident.resolved_at = utcnow()


def on_incident_opened(service: Service, incident: Incident) -> None:
    from app.services import jobs, notifications  # local import: avoid cycles

    jobs.enqueue_analysis(incident.id)
    if not service.is_test:
        notifications.notify_incident_opened(service, incident)


def on_incident_resolved(service: Service, incident: Incident) -> None:
    from app.services import notifications

    if not service.is_test:
        notifications.notify_incident_resolved(service, incident)
