from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Check


@dataclass
class ServiceAggregate:
    service_id: int
    total: int
    available: int
    avg_ms: float | None


def add(db: Session, check: Check) -> Check:
    db.add(check)
    db.flush()
    return check


def recent(db: Session, service_id: int, limit: int = 5) -> list[Check]:
    """Most recent checks, newest first."""
    stmt = (select(Check).where(Check.service_id == service_id)
            .order_by(Check.checked_at.desc(), Check.id.desc()).limit(limit))
    return list(db.scalars(stmt))


def page(db: Session, service_id: int, page_num: int, size: int) -> tuple[list[Check], int]:
    total = db.scalar(select(func.count()).select_from(Check).where(Check.service_id == service_id)) or 0
    stmt = (select(Check).where(Check.service_id == service_id)
            .order_by(Check.checked_at.desc(), Check.id.desc())
            .offset((page_num - 1) * size).limit(size))
    return list(db.scalars(stmt)), total


def since(db: Session, service_id: int, start: datetime, limit: int = 5000) -> list[Check]:
    stmt = (select(Check).where(Check.service_id == service_id, Check.checked_at >= start)
            .order_by(Check.checked_at.asc()).limit(limit))
    return list(db.scalars(stmt))


def aggregates_since(db: Session, start: datetime) -> dict[int, ServiceAggregate]:
    stmt = (select(Check.service_id,
                   func.count(Check.id),
                   func.sum(case((Check.status != "down", 1), else_=0)),
                   func.avg(case((Check.status != "down", Check.duration_ms), else_=None)))
            .where(Check.checked_at >= start)
            .group_by(Check.service_id))
    result: dict[int, ServiceAggregate] = {}
    for service_id, total, available, avg_ms in db.execute(stmt):
        result[service_id] = ServiceAggregate(service_id, int(total or 0), int(available or 0),
                                              float(avg_ms) if avg_ms is not None else None)
    return result
