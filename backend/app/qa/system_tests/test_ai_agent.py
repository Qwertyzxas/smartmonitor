from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import settings
from app.services import ai_agent

MOCK_CHECKS_TIMEOUT = [{"status": "down", "status_code": None, "duration_ms": 10000.0,
                        "error": "Timeout after 10s", "error_kind": "timeout", "body_snippet": None}] * 5
MOCK_CHECKS_DB = [{"status": "down", "status_code": 500, "duration_ms": 3200.0, "error": "HTTP 500",
                   "error_kind": None,
                   "body_snippet": "database error: could not connect to postgres, too many connections"}] * 5
MOCK_CHECKS_502 = [{"status": "down", "status_code": 502, "duration_ms": 80.0, "error": "HTTP 502",
                    "error_kind": None, "body_snippet": "Bad Gateway"}] * 5


def make_ctx(checks: list[dict]) -> ai_agent.AgentContext:
    return ai_agent.AgentContext(service_name="mock-api", url="https://mock.local/health", incident_id=None,
                                 incident_reason="HTTP 5xx", started_at="2026-01-01T00:00:00Z",
                                 failed_checks=len(checks), auto_actions_allowed=True, checks=checks,
                                 previous_actions=[])


def mock_openrouter(answer: str) -> ai_agent.OpenRouterClient:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["messages"][0]["role"] == "system"
        assert "mock-api" in body["messages"][1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": answer}}]})

    return ai_agent.OpenRouterClient("test-key", "mock/model", transport=httpx.MockTransport(handler))


def test_agent_parses_structured_command_from_llm() -> None:
    answer = ("```json\n" + json.dumps({
        "problem_type": "server", "severity": "high", "summary": "502 от upstream",
        "recommendation": "Перезапустить приложение", "command": {"action": "restart", "target": "mock-api"},
    }, ensure_ascii=False) + "\n```")
    decision, exchange = ai_agent.ask_llm(make_ctx(MOCK_CHECKS_502), mock_openrouter(answer))
    assert decision.command.action == "restart"
    assert decision.problem_type == "server"
    assert exchange.success and exchange.parsed is not None


def test_agent_raises_on_garbage_so_fallback_is_used() -> None:
    with pytest.raises(ai_agent.AgentError) as err:
        ai_agent.ask_llm(make_ctx(MOCK_CHECKS_502), mock_openrouter("I am not JSON at all"))
    assert err.value.exchange.success is False


@pytest.mark.parametrize("checks,expected", [
    (MOCK_CHECKS_TIMEOUT, "network"),
    (MOCK_CHECKS_DB, "database"),
    (MOCK_CHECKS_502, "server"),
])
def test_fallback_classifier(checks: list[dict], expected: str) -> None:
    decision, exchange = ai_agent.fallback_decision(make_ctx(checks))
    assert decision.problem_type == expected
    assert exchange.provider == "fallback"
    assert decision.command.action in {"restart", "scale_up", "notify_admin"}


@pytest.mark.skipif(not settings.openrouter_enabled or not settings.qa_live_llm,
                    reason="OPENROUTER_API_KEY not configured or QA_LIVE_LLM=false")
def test_openrouter_live_responds() -> None:
    decision, exchange = ai_agent.ask_llm(make_ctx(MOCK_CHECKS_502), ai_agent.OpenRouterClient.from_settings())
    assert exchange.success
    assert decision.recommendation
