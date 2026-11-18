from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User


def get(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.username) == username.lower()))


def create(db: Session, username: str, password_hash: str, role: str) -> User:
    user = User(username=username, password_hash=password_hash, role=role)
    db.add(user)
    db.flush()
    return user


def list_all(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)))


def count_admins(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.role == "admin")) or 0
