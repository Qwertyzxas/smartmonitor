from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models import UserRole
from app.repositories import services as services_repo
from app.repositories import users as users_repo


def seed(db: Session) -> None:
    if users_repo.get_by_username(db, settings.admin_username) is None:
        users_repo.create(db, settings.admin_username, hash_password(settings.admin_password),
                          UserRole.admin.value)
        logger.info("Created admin user '{}'", settings.admin_username)

    if settings.seed_demo and not services_repo.list_all(db, include_test=True):
        base = settings.backend_internal_url.rstrip("/")
        demo = [
            dict(name="Example.com", url="https://example.com/", interval_seconds=60),
            dict(name="GitHub API", url="https://api.github.com/", interval_seconds=120,
                 slow_threshold_ms=1500),
            dict(name="Cloudflare DNS", url="https://1.1.1.1/", interval_seconds=90),
            dict(name="Demo-сервис (симулятор)", url=f"{base}/api/sim/demo", interval_seconds=20,
                 timeout_seconds=5, slow_threshold_ms=1500, auto_actions_enabled=True),
        ]
        for fields in demo:
            services_repo.create(db, **fields)
        logger.info("Seeded {} demo services", len(demo))
    db.commit()
