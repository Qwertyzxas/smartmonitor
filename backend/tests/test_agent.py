from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import settings
from app.models import Check, Incident, Service, utcnow
from app.repositories import conversations as conv_repo
from app.repositories import settings_repo
from app.services import ai_agent
from app.services.ai_agent import parse_decision


def _client(content: str | None = None, fail: bool = False) -> ai_agent.OpenRouterClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if fail:
            return httpx.Response(502, text="upstream error")
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return ai_agent.OpenRouterClient("k", "test/model", transport=httpx.MockTransport(handler))


def _incident(db, auto: bool = True, body: str = "Bad Gateway", code: int = 502) -> Incident:  # type: ignore[no-untyped-def]
    svc = Service(name="api", url="https://api.test/", auto_actions_enabled=auto)
    db.add(svc)
    db.flush()
    for _ in range(3):
        db.add(Check(service_id=svc.id, status="down", status_code=code, duration_ms=50,
                     response_body=body, checked_at=utcnow()))
    inc = Incident(service_id=svc.id, reason=f"HTTP {code}", failed_checks=3)
    db.add(inc)
    db.commit()
    return inc


DECISION = json.dumps({"problem_type": "server", "severity": "high", "summary": "Upstream 502",
                       "recommendation": "Перезапустить сервис", "command": {"action": "restart"}})


def test_parse_decision_variants() -> None:
    assert parse_decision(DECISION).command.action == "restart"
    assert parse_decision(f"Вот ответ:\n```json\n{DECISION}\n```").problem_type == "server"
    weird = parse_decision('{"problem_type": "alien", "recommendation": "x", "command": "explode"}')
    assert weird.problem_type == "unknown" and weird.command.action == "none"
    with pytest.raises(ValueError):
        parse_decision("no json here")


@pytest.fixture()
def llm_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")


def test_auto_action_executed_when_allowed(db, llm_on) -> None:  # type: ignore[no-untyped-def]
    settings_repo.set_value(db, "auto_actions_enabled", True)
    inc = _incident(db, auto=True)
    action = ai_agent.analyze_incident(db, inc.id, client=_client(DECISION))
    assert action is not None
    assert action.source == "openrouter"
    assert action.command == "restart"
    assert action.status == "executed" and action.auto is True and action.executed_at is not None
    db.refresh(inc)
    assert inc.problem_type == "server"
    convs = conv_repo.for_incident(db, inc.id)
    assert len(convs) == 1 and convs[0].success and convs[0].request["messages"]


def test_dangerous_action_waits_without_permission(db, llm_on) -> None:  # type: ignore[no-untyped-def]
    inc = _incident(db, auto=True)  # global switch is off by default
    action = ai_agent.analyze_incident(db, inc.id, client=_client(DECISION))
    assert action is not None and action.status == "suggested"


def test_fallback_when_openrouter_fails(db, llm_on) -> None:  # type: ignore[no-untyped-def]
    inc = _incident(db, body="database error: too many connections to postgres", code=500)
    action = ai_agent.analyze_incident(db, inc.id, client=_client(fail=True))
    assert action is not None
    assert action.source == "fallback"
    assert action.problem_type == "database"
    convs = conv_repo.for_incident(db, inc.id)
    assert [c.provider for c in convs] == ["openrouter", "fallback"]
    assert convs[0].success is False and "502" in (convs[0].error or "")


def test_fallback_without_key(db) -> None:  # type: ignore[no-untyped-def]
    inc = _incident(db)
    action = ai_agent.analyze_incident(db, inc.id)
    assert action is not None and action.source == "fallback"
