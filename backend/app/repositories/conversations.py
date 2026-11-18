from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AIConversation


def add(db: Session, conversation: AIConversation) -> AIConversation:
    db.add(conversation)
    db.flush()
    return conversation


def get(db: Session, conversation_id: int) -> AIConversation | None:
    return db.get(AIConversation, conversation_id)


def for_incident(db: Session, incident_id: int) -> list[AIConversation]:
    return list(db.scalars(select(AIConversation).where(AIConversation.incident_id == incident_id)
                           .order_by(AIConversation.id)))


def page(db: Session, page_num: int, size: int, provider: str | None = None) -> tuple[list[AIConversation], int]:
    stmt = select(AIConversation)
    count_stmt = select(func.count()).select_from(AIConversation)
    if provider:
        stmt = stmt.where(AIConversation.provider == provider)
        count_stmt = count_stmt.where(AIConversation.provider == provider)
    total = db.scalar(count_stmt) or 0
    stmt = stmt.order_by(AIConversation.created_at.desc()).offset((page_num - 1) * size).limit(size)
    return list(db.scalars(stmt)), total
