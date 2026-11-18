from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from loguru import logger
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings


def _make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url.endswith("sqlite://"):
            kwargs["poolclass"] = StaticPool
        sqlite_engine = create_engine(url, **kwargs)

        @event.listens_for(sqlite_engine, "connect")
        def _enable_fk(dbapi_conn: Any, _record: Any) -> None:
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return sqlite_engine
    return create_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)


engine: Engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def wait_for_db(attempts: int = 30, delay: float = 2.0) -> None:
    for i in range(1, attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:
            logger.warning("Database is not ready ({}/{}): {}", i, attempts, exc)
            time.sleep(delay)
    raise RuntimeError("Database is unavailable")


def init_db() -> None:
    from app.models import Base

    Base.metadata.create_all(bind=engine)
