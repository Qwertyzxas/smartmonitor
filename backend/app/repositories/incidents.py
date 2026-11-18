from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import Incident, IncidentStatus


def get(db: Session, incident_id: int) -> Incident | None:
    return db.scalar(select(Incident).options(joinedload(Incident.service))
                     .where(Incident.id == incident_id))


def get_open(db: Session, service_id: int) -> Incident | None:
    stmt = (select(Incident)
            .where(Incident.service_id == service_id, Incident.status == IncidentStatus.open.value)
            .order_by(Incident.started_at.desc()).limit(1))
    return db.scalar(stmt)


def open_map(db: Session) -> dict[int, int]:
    rows = db.execute(select(Incident.service_id, func.max(Incident.id))
                      .where(Incident.status == IncidentStatus.open.value)
                      .group_by(Incident.service_id))
    return {sid: iid for sid, iid in rows}


def add(db: Session, incident: Incident) -> Incident:
    db.add(incident)
    db.flush()
    return incident


def page(db: Session, page_num: int, size: int, status: str | None = None,
         service_id: int | None = None) -> tuple[list[Incident], int]:
    stmt = select(Incident).options(joinedload(Incident.service))
    count_stmt = select(func.count()).select_from(Incident)
    if status:
        stmt = stmt.where(Incident.status == status)
        count_stmt = count_stmt.where(Incident.status == status)
    if service_id:
        stmt = stmt.where(Incident.service_id == service_id)
        count_stmt = count_stmt.where(Incident.service_id == service_id)
    total = db.scalar(count_stmt) or 0
    stmt = stmt.order_by(Incident.started_at.desc()).offset((page_num - 1) * size).limit(size)
    return list(db.scalars(stmt).unique()), total


def count_open(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Incident)
                     .where(Incident.status == IncidentStatus.open.value)) or 0


def count_since(db: Session, start: datetime) -> int:
    return db.scalar(select(func.count()).select_from(Incident).where(Incident.started_at >= start)) or 0
