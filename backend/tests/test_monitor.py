from __future__ import annotations

import httpx

from app.models import CheckStatus, Service
from app.repositories import incidents as incidents_repo
from app.services import monitor
from app.services.monitor import ProbeResult, evaluate


def test_evaluate_statuses() -> None:
    assert evaluate(ProbeResult(200, 120), 2000, []).status == CheckStatus.up
    assert evaluate(ProbeResult(503, 50), 2000, []).status == CheckStatus.down
    assert evaluate(ProbeResult(404, 50), 2000, []).status == CheckStatus.down
    assert evaluate(ProbeResult(200, 2500), 2000, []).status == CheckStatus.degraded
    assert evaluate(ProbeResult(None, 10000, "t/o", "timeout"), 2000, []).status == CheckStatus.down


def test_evaluate_detects_speed_spike() -> None:
    result = evaluate(ProbeResult(200, 1500), 2000, [100, 120, 110, 90])
    assert result.status == CheckStatus.degraded
    assert "spike" in result.reason.lower()


def _service(db) -> Service:  # type: ignore[no-untyped-def]
    svc = Service(name="svc", url="https://svc.test/", interval_seconds=60, timeout_seconds=5,
                  slow_threshold_ms=2000)
    db.add(svc)
    db.commit()
    return svc


def _transport(status: int) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status, text="ok" if status < 400 else "fail"))


def test_incident_lifecycle(db) -> None:  # type: ignore[no-untyped-def]
    svc = _service(db)

    first = monitor.run_check(db, svc, transport=_transport(503))
    assert first.check.status == "down"
    assert first.incident_opened_id is None  # one failure is not an incident yet

    second = monitor.run_check(db, svc, transport=_transport(503))
    assert second.incident_opened_id is not None
    incident = incidents_repo.get(db, second.incident_opened_id)
    assert incident is not None and incident.status == "open" and incident.failed_checks == 2

    third = monitor.run_check(db, svc, transport=_transport(500))
    assert third.incident_opened_id is None  # still the same incident
    db.refresh(incident)
    assert incident.failed_checks == 3

    recovered = monitor.run_check(db, svc, transport=_transport(200))
    assert recovered.incident_resolved_id == incident.id
    db.refresh(incident)
    assert incident.status == "resolved" and incident.resolved_at is not None
    assert svc.current_status == "up"


def test_timeout_probe() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    result = monitor.probe("https://x.test", 1, transport=httpx.MockTransport(boom))
    assert result.error_kind == "timeout"
