from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import TestRun


def add(db: Session, run: TestRun) -> TestRun:
    db.add(run)
    db.flush()
    return run


def get(db: Session, run_id: int) -> TestRun | None:
    return db.get(TestRun, run_id)


def latest(db: Session) -> TestRun | None:
    return db.scalar(select(TestRun).order_by(TestRun.started_at.desc()).limit(1))


def page(db: Session, page_num: int, size: int) -> tuple[list[TestRun], int]:
    total = db.scalar(select(func.count()).select_from(TestRun)) or 0
    stmt = select(TestRun).order_by(TestRun.started_at.desc()).offset((page_num - 1) * size).limit(size)
    return list(db.scalars(stmt)), total


def recent(db: Session, limit: int = 50) -> list[TestRun]:
    return list(db.scalars(select(TestRun).order_by(TestRun.started_at.desc()).limit(limit)))
