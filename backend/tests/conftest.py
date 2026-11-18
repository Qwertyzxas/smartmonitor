"""Unit/integration tests running on in-memory SQLite without Redis/Celery."""
from __future__ import annotations

import os
import tempfile

os.environ.update({
    "DATABASE_URL": "sqlite:///:memory:",
    "CELERY_EAGER": "true",
    "SEED_DEMO": "false",
    "OPENROUTER_API_KEY": "",
    "TELEGRAM_BOT_TOKEN": "",
    "ADMIN_USERNAME": "admin",
    "ADMIN_PASSWORD": "admin123",
    "JWT_SECRET": "unit-test-secret",
    "LOG_DIR": os.path.join(tempfile.gettempdir(), "smartmonitor-test-logs"),
})

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import cache  # noqa: E402
from app.core.database import SessionLocal, engine  # noqa: E402
from app.models import Base  # noqa: E402
from app.services import jobs  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    cache._memory.clear()  # noqa: SLF001
    # incident analysis is exercised explicitly; don't spawn background threads
    monkeypatch.setattr(jobs, "enqueue_analysis", lambda incident_id: "noop")
    yield


@pytest.fixture()
def db() -> Iterator:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client() -> Iterator[TestClient]:
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def admin_headers(client: TestClient) -> dict[str, str]:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def viewer_headers(client: TestClient) -> dict[str, str]:
    r = client.post("/api/auth/register", json={"username": "viewer1", "password": "secret123"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
