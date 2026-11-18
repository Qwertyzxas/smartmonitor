from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppSetting

DEFAULTS: dict[str, Any] = {
    "auto_actions_enabled": False,
    "ai_enabled": True,
    "telegram_notifications": True,
}


def get_all(db: Session) -> dict[str, AppSetting]:
    return {s.key: s for s in db.scalars(select(AppSetting))}


def get_value(db: Session, key: str) -> Any:
    row = db.get(AppSetting, key)
    return row.value if row is not None else DEFAULTS.get(key)


def set_value(db: Session, key: str, value: Any, user_id: int | None = None) -> AppSetting:
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value, updated_by_id=user_id)
        db.add(row)
    else:
        row.value = value
        row.updated_by_id = user_id
    db.flush()
    return row
