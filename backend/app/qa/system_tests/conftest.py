from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import httpx
import pytest

from app.core.config import settings

BASE_URL = os.getenv("QA_BACKEND_URL", settings.backend_internal_url).rstrip("/")
VIEWER_NAME = "qa_viewer"
VIEWER_PASSWORD = os.getenv("QA_VIEWER_PASSWORD", "qa-viewer-password")


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        yield c


@pytest.fixture(scope="session")
def admin_headers(client: httpx.Client) -> dict[str, str]:
    r = client.post("/api/auth/login", json={"username": settings.admin_username,
                                              "password": settings.admin_password})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def viewer_headers(client: httpx.Client) -> dict[str, str]:
    creds = {"username": VIEWER_NAME, "password": VIEWER_PASSWORD}
    r = client.post("/api/auth/login", json=creds)
    if r.status_code == 401:
        r = client.post("/api/auth/register", json=creds)
    assert r.status_code in (200, 201), r.text
    assert r.json()["user"]["role"] == "viewer"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def temp_service(client: httpx.Client, admin_headers: dict[str, str], base_url: str) -> Iterator[dict]:
    sim_name = f"qa-{uuid.uuid4().hex[:8]}"
    client.put(f"/api/sim/{sim_name}", json={"mode": "up"}, headers=admin_headers).raise_for_status()
    r = client.post("/api/services", headers=admin_headers, json={
        "name": f"[QA] {sim_name}", "url": f"{base_url}/api/sim/{sim_name}", "interval_seconds": 3600,
        "timeout_seconds": 5, "slow_threshold_ms": 3000, "is_active": False, "is_test": True,
    })
    assert r.status_code == 201, r.text
    service = r.json() | {"sim_name": sim_name}
    yield service
    client.delete(f"/api/services/{service['id']}", headers=admin_headers)
