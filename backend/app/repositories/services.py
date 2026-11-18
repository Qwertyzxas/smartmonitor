from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Service


def get(db: Session, service_id: int) -> Service | None:
    return db.get(Service, service_id)


def list_all(db: Session, include_test: bool = False) -> list[Service]:
    stmt = select(Service).order_by(Service.id)
    if not include_test:
        stmt = stmt.where(Service.is_test.is_(False))
    return list(db.scalars(stmt))


def list_active(db: Session) -> list[Service]:
    return list(db.scalars(select(Service).where(Service.is_active.is_(True)).order_by(Service.id)))


def create(db: Session, **fields: Any) -> Service:
    service = Service(**fields)
    db.add(service)
    db.flush()
    return service


def update(db: Session, service: Service, **fields: Any) -> Service:
    for key, value in fields.items():
        setattr(service, key, value)
    db.flush()
    return service


def delete(db: Session, service: Service) -> None:
    db.delete(service)
    db.flush()
