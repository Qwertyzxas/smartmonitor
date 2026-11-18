from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Action


def get(db: Session, action_id: int) -> Action | None:
    return db.get(Action, action_id)


def add(db: Session, action: Action) -> Action:
    db.add(action)
    db.flush()
    return action


def for_incident(db: Session, incident_id: int) -> list[Action]:
    return list(db.scalars(select(Action).where(Action.incident_id == incident_id).order_by(Action.id)))


def history_for_service(db: Session, service_id: int, limit: int = 5) -> list[Action]:
    stmt = (select(Action).where(Action.service_id == service_id)
            .order_by(Action.created_at.desc()).limit(limit))
    return list(db.scalars(stmt))


def page(db: Session, page_num: int, size: int, status: str | None = None) -> tuple[list[Action], int]:
    stmt = select(Action)
    count_stmt = select(func.count()).select_from(Action)
    if status:
        stmt = stmt.where(Action.status == status)
        count_stmt = count_stmt.where(Action.status == status)
    total = db.scalar(count_stmt) or 0
    stmt = stmt.order_by(Action.created_at.desc()).offset((page_num - 1) * size).limit(size)
    return list(db.scalars(stmt)), total


def count_since(db: Session, start: datetime) -> int:
    return db.scalar(select(func.count()).select_from(Action).where(Action.created_at >= start)) or 0
