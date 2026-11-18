from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import monitor
from app.services.monitor import ProbeResult


@pytest.fixture()
def fake_probe(monkeypatch: pytest.MonkeyPatch) -> dict[str, ProbeResult]:
    state = {"result": ProbeResult(200, 123.0, body="ok")}
    monkeypatch.setattr(monitor, "probe", lambda url, timeout, transport=None: state["result"])
    return state


def test_auth_flow(client: TestClient) -> None:
    assert client.get("/api/services").status_code == 401
    assert client.post("/api/auth/login", json={"username": "admin", "password": "nope123"}).status_code == 401
    r = client.post("/api/auth/register", json={"username": "bob", "password": "secret123"})
    assert r.status_code == 201 and r.json()["user"]["role"] == "viewer"
    assert client.post("/api/auth/register", json={"username": "bob", "password": "secret123"}).status_code == 409
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.json()["username"] == "bob"


def test_viewer_is_read_only(client: TestClient, viewer_headers: dict[str, str]) -> None:
    assert client.get("/api/services", headers=viewer_headers).status_code == 200
    assert client.post("/api/services", headers=viewer_headers,
                       json={"name": "x", "url": "https://x.test"}).status_code == 403
    assert client.put("/api/settings", headers=viewer_headers, json={"ai_enabled": False}).status_code == 403
    assert client.get("/api/ai/conversations", headers=viewer_headers).status_code == 403


def test_service_crud_and_manual_check(client: TestClient, admin_headers: dict[str, str],
                                       fake_probe: dict[str, ProbeResult]) -> None:
    r = client.post("/api/services", headers=admin_headers,
                    json={"name": "Example", "url": "https://example.com", "interval_seconds": 30})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]

    check = client.post(f"/api/services/{sid}/check", headers=admin_headers)
    assert check.status_code == 200 and check.json()["check"]["status"] == "up"

    listing = client.get("/api/services", headers=admin_headers).json()
    assert listing[0]["uptime_24h"] == 100.0 and listing[0]["checks_24h"] == 1

    fake_probe["result"] = ProbeResult(503, 40.0, body="unavailable")
    client.post("/api/checks", headers=admin_headers, json={"service_id": sid})
    second = client.post("/api/checks", headers=admin_headers, json={"service_id": sid}).json()
    assert second["incident_opened"]

    incidents = client.get("/api/incidents?status=open", headers=admin_headers).json()
    assert incidents["total"] == 1 and incidents["items"][0]["service_name"] == "Example"

    summary = client.get("/api/stats/summary", headers=admin_headers).json()
    assert summary["open_incidents"] == 1 and summary["down"] == 1

    series = client.get(f"/api/services/{sid}/timeseries", headers=admin_headers).json()
    assert len(series) == 3

    page = client.get(f"/api/services/{sid}/checks?page=1&size=2", headers=admin_headers).json()
    assert page["total"] == 3 and len(page["items"]) == 2

    upd = client.put(f"/api/services/{sid}", headers=admin_headers, json={"auto_actions_enabled": True})
    assert upd.json()["auto_actions_enabled"] is True

    assert client.delete(f"/api/services/{sid}", headers=admin_headers).status_code == 204
    assert client.get(f"/api/services/{sid}", headers=admin_headers).status_code == 404


def test_analyze_and_manual_execute(client: TestClient, admin_headers: dict[str, str],
                                    fake_probe: dict[str, ProbeResult]) -> None:
    sid = client.post("/api/services", headers=admin_headers,
                      json={"name": "Api", "url": "https://api.test"}).json()["id"]
    fake_probe["result"] = ProbeResult(502, 30.0, body="Bad Gateway")
    client.post(f"/api/services/{sid}/check", headers=admin_headers)
    inc_id = client.post(f"/api/services/{sid}/check", headers=admin_headers).json()["incident_opened"]

    res = client.post(f"/api/incidents/{inc_id}/analyze", headers=admin_headers).json()
    assert res["status"] == "done"
    detail = client.get(f"/api/incidents/{inc_id}", headers=admin_headers).json()
    action = detail["actions"][0]
    assert action["source"] == "fallback" and action["recommendation"]
    assert action["command"] == "restart" and action["status"] == "suggested"

    executed = client.post(f"/api/actions/{action['id']}/execute", headers=admin_headers).json()
    assert executed["status"] == "executed" and executed["auto"] is False

    convs = client.get("/api/ai/conversations", headers=admin_headers).json()
    assert convs["total"] == 1 and convs["items"][0]["provider"] == "fallback"


def test_settings_and_simulator(client: TestClient, admin_headers: dict[str, str]) -> None:
    s = client.put("/api/settings", headers=admin_headers, json={"auto_actions_enabled": True}).json()
    assert s["auto_actions_enabled"] is True and s["updated_by"] == "admin"

    assert client.get("/api/sim/demo").status_code == 200
    client.put("/api/sim/demo", headers=admin_headers, json={"mode": "down"})
    assert client.get("/api/sim/demo").status_code == 503
    client.put("/api/sim/demo", headers=admin_headers, json={"mode": "db_error"})
    r = client.get("/api/sim/demo")
    assert r.status_code == 500 and "database" in r.text


def test_role_management(client: TestClient, admin_headers: dict[str, str],
                         viewer_headers: dict[str, str]) -> None:
    users = client.get("/api/users", headers=admin_headers).json()
    viewer = next(u for u in users if u["username"] == "viewer1")
    r = client.patch(f"/api/users/{viewer['id']}", headers=admin_headers, json={"role": "admin"})
    assert r.json()["role"] == "admin"
    admin = next(u for u in users if u["username"] == "admin")
    assert client.patch(f"/api/users/{admin['id']}", headers=admin_headers,
                        json={"role": "viewer"}).status_code == 400
