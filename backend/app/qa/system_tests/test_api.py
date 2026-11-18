from __future__ import annotations

import httpx


def test_health(client: httpx.Client) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["database"] is True
    assert body["redis"] is True


def test_login_rejects_bad_password(client: httpx.Client) -> None:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "definitely-wrong"})
    assert r.status_code == 401


def test_services_requires_auth(client: httpx.Client) -> None:
    assert client.get("/api/services").status_code == 401


def test_get_services(client: httpx.Client, viewer_headers: dict[str, str]) -> None:
    r = client.get("/api/services", headers=viewer_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_viewer_cannot_modify(client: httpx.Client, viewer_headers: dict[str, str]) -> None:
    r = client.post("/api/services", headers=viewer_headers,
                    json={"name": "nope", "url": "https://example.com"})
    assert r.status_code == 403
    assert client.put("/api/settings", headers=viewer_headers,
                      json={"auto_actions_enabled": True}).status_code == 403


def test_summary(client: httpx.Client, viewer_headers: dict[str, str]) -> None:
    r = client.get("/api/stats/summary", headers=viewer_headers)
    assert r.status_code == 200
    assert "services_total" in r.json()


def test_post_check_saves_result(client: httpx.Client, admin_headers: dict[str, str], temp_service: dict) -> None:
    r = client.post("/api/checks", headers=admin_headers, json={"service_id": temp_service["id"]})
    assert r.status_code == 200, r.text
    check = r.json()["check"]
    assert check["status"] == "up"
    assert check["status_code"] == 200

    history = client.get(f"/api/services/{temp_service['id']}/checks", headers=admin_headers).json()
    assert history["total"] == 1
    assert history["items"][0]["id"] == check["id"]

    series = client.get(f"/api/services/{temp_service['id']}/timeseries", headers=admin_headers).json()
    assert len(series) == 1 and series[0]["ms"] is not None


def test_incident_opens_after_two_failures_and_resolves(client: httpx.Client, admin_headers: dict[str, str],
                                                       temp_service: dict) -> None:
    sid, sim = temp_service["id"], temp_service["sim_name"]
    client.put(f"/api/sim/{sim}", json={"mode": "down"}, headers=admin_headers).raise_for_status()

    first = client.post(f"/api/services/{sid}/check", headers=admin_headers).json()
    assert first["check"]["status"] == "down"
    assert first["incident_opened"] is None

    second = client.post(f"/api/services/{sid}/check", headers=admin_headers).json()
    assert second["incident_opened"], "incident must open after 2 consecutive failures"

    incident = client.get(f"/api/incidents/{second['incident_opened']}", headers=admin_headers).json()
    assert incident["status"] == "open"
    assert incident["service_id"] == sid

    client.put(f"/api/sim/{sim}", json={"mode": "up"}, headers=admin_headers).raise_for_status()
    third = client.post(f"/api/services/{sid}/check", headers=admin_headers).json()
    assert third["incident_resolved"] == incident["id"]
