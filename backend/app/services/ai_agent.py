from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace
from typing import Any

import httpx
from loguru import logger
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core import cache
from app.core.config import settings
from app.core.logging import audit_logger
from app.models import AIConversation, Action, ActionStatus, Check, Incident, Service
from app.repositories import actions as actions_repo
from app.repositories import checks as checks_repo
from app.repositories import conversations as conv_repo
from app.repositories import incidents as incidents_repo
from app.repositories import settings_repo
from app.schemas import AgentCommandModel, AgentDecision
from app.services import classifier, executor

FALLBACK_MODEL = "sklearn-random-forest"

SYSTEM_PROMPT = """Ты — SRE-агент платформы мониторинга SmartMonitor.
Тебе передают инцидент по внешнему HTTP-сервису: URL, последние проверки и историю прошлых действий.
Определи вероятную причину, дай короткую практичную рекомендацию на русском языке и предложи ОДНУ команду.

Доступные команды:
- "restart"       — перезапуск сервиса (опасная команда)
- "scale_up"      — увеличить число инстансов/ресурсов (опасная команда)
- "notify_admin"  — уведомить дежурного администратора (безопасная)
- "none"          — ничего не делать (проблема сама ушла / недостаточно данных)

Если в контексте auto_actions_allowed = false, опасные команды всё равно можно предлагать, но они
будут выполнены только после подтверждения администратором. Не повторяй действие, которое уже
не помогло в истории, без веской причины.

Ответь СТРОГО одним JSON-объектом без пояснений и без markdown, по схеме:
{
  "problem_type": "network" | "server" | "database" | "performance" | "unknown",
  "severity": "low" | "medium" | "high" | "critical",
  "summary": "одно предложение: что происходит",
  "recommendation": "2-4 предложения: что проверить и что сделать",
  "command": {"action": "restart" | "scale_up" | "notify_admin" | "none",
              "target": "<имя сервиса>", "params": {}, "reason": "почему эта команда"}
}"""


class AgentError(Exception):
    def __init__(self, message: str, exchange: "LLMExchange") -> None:
        super().__init__(message)
        self.exchange = exchange


@dataclass
class AgentContext:
    service_name: str
    url: str
    incident_id: int | None
    incident_reason: str
    started_at: str
    failed_checks: int
    auto_actions_allowed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    previous_actions: list[dict[str, Any]] = field(default_factory=list)

    def to_prompt_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LLMExchange:
    provider: str
    model: str
    request: dict[str, Any]
    response: str | None = None
    parsed: dict[str, Any] | None = None
    success: bool = False
    error: str | None = None
    latency_ms: float | None = None


class OpenRouterClient:
    def __init__(self, api_key: str, model: str, base_url: str = "https://openrouter.ai/api/v1",
                 timeout: float = 40.0, transport: httpx.BaseTransport | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    @classmethod
    def from_settings(cls) -> "OpenRouterClient":
        return cls(settings.openrouter_api_key, settings.openrouter_model, settings.openrouter_base_url,
                   settings.openrouter_timeout)

    def chat(self, messages: list[dict[str, str]], max_tokens: int = 700) -> tuple[str, dict[str, Any]]:
        payload = {"model": self.model, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/smartmonitor",
            "X-Title": "SmartMonitor",
        }
        with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
            response = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
        if response.status_code >= 400:
            raise RuntimeError(f"OpenRouter HTTP {response.status_code}: {response.text[:300]}")
        data: dict[str, Any] = response.json()
        if "error" in data:
            raise RuntimeError(f"OpenRouter error: {data['error']}")
        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected OpenRouter response: {str(data)[:300]}") from exc
        return content, data


def check_to_dict(check: Check) -> dict[str, Any]:
    return {
        "checked_at": check.checked_at.isoformat() if check.checked_at else None,
        "status": check.status,
        "status_code": check.status_code,
        "duration_ms": check.duration_ms,
        "error": check.error,
        "error_kind": check.error_kind,
        "body_snippet": (check.response_body or "")[:200] or None,
    }


def action_to_dict(action: Action) -> dict[str, Any]:
    return {
        "created_at": action.created_at.isoformat() if action.created_at else None,
        "incident_id": action.incident_id,
        "problem_type": action.problem_type,
        "command": action.command,
        "status": action.status,
        "result": (action.result or "")[:200] or None,
    }


def build_messages(ctx: AgentContext) -> list[dict[str, str]]:
    user = ("Контекст инцидента (JSON):\n"
            + json.dumps(ctx.to_prompt_dict(), ensure_ascii=False, indent=2, default=str)
            + "\n\nВерни только JSON по схеме.")
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_decision(content: str) -> AgentDecision:
    text = content.strip()
    candidates: list[str] = []
    fence = _JSON_FENCE.search(text)
    if fence:
        candidates.append(fence.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    candidates.append(text)

    last_error: Exception | None = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data.get("command"), str):
                data["command"] = {"action": data["command"]}
            if not data.get("recommendation") and data.get("summary"):
                data["recommendation"] = data["summary"]
            return AgentDecision.model_validate(data)
        except (json.JSONDecodeError, ValidationError, AttributeError) as exc:
            last_error = exc
    raise ValueError(f"Cannot parse agent answer as JSON decision: {last_error}")


def ask_llm(ctx: AgentContext, client: OpenRouterClient) -> tuple[AgentDecision, LLMExchange]:
    messages = build_messages(ctx)
    exchange = LLMExchange(provider="openrouter", model=client.model, request={"messages": messages})
    started = time.perf_counter()
    try:
        content, _raw = client.chat(messages)
        exchange.response = content
        decision = parse_decision(content)
    except Exception as exc:
        exchange.latency_ms = round((time.perf_counter() - started) * 1000, 1)
        exchange.error = f"{exc.__class__.__name__}: {exc}"[:2000]
        raise AgentError(str(exc), exchange) from exc
    exchange.latency_ms = round((time.perf_counter() - started) * 1000, 1)
    exchange.parsed = decision.model_dump()
    exchange.success = True
    return decision, exchange


def fallback_decision(ctx: AgentContext, reason: str | None = None) -> tuple[AgentDecision, LLMExchange]:
    started = time.perf_counter()
    checks = [SimpleNamespace(status_code=c.get("status_code"), duration_ms=c.get("duration_ms"),
                              error=c.get("error"), error_kind=c.get("error_kind"),
                              response_body=c.get("body_snippet")) for c in ctx.checks]
    result = classifier.classify(checks)
    text, command, severity = classifier.RECOMMENDATIONS[result.label]
    decision = AgentDecision.model_validate({
        "problem_type": result.label,
        "severity": severity,
        "summary": f"Локальный классификатор: проблема типа «{result.label}» "
                   f"(уверенность {result.confidence:.0%}). {ctx.incident_reason}",
        "recommendation": text,
        "command": {"action": command, "target": ctx.service_name,
                    "reason": f"fallback classifier → {result.label}"},
    })
    exchange = LLMExchange(
        provider="fallback", model=FALLBACK_MODEL,
        request={"features": result.features, "context": ctx.to_prompt_dict(), "fallback_reason": reason},
        response=json.dumps({"label": result.label, "probabilities": result.probabilities}, ensure_ascii=False),
        parsed=decision.model_dump(), success=True,
        latency_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return decision, exchange


def build_context(db: Session, incident: Incident, service: Service, auto_allowed: bool) -> AgentContext:
    recent = checks_repo.recent(db, service.id, limit=5)
    history = actions_repo.history_for_service(db, service.id, limit=5)
    return AgentContext(
        service_name=service.name, url=service.url, incident_id=incident.id,
        incident_reason=incident.reason, started_at=incident.started_at.isoformat(),
        failed_checks=incident.failed_checks, auto_actions_allowed=auto_allowed,
        checks=[check_to_dict(c) for c in recent],
        previous_actions=[action_to_dict(a) for a in history],
    )


def _save_exchange(db: Session, exchange: LLMExchange, incident: Incident) -> AIConversation:
    return conv_repo.add(db, AIConversation(
        incident_id=incident.id, service_id=incident.service_id, provider=exchange.provider,
        model=exchange.model, request=exchange.request, response=exchange.response,
        parsed=exchange.parsed, success=exchange.success, error=exchange.error,
        latency_ms=exchange.latency_ms,
    ))


def auto_actions_allowed(db: Session, service: Service) -> bool:
    return bool(settings_repo.get_value(db, "auto_actions_enabled")) and service.auto_actions_enabled


def analyze_incident(db: Session, incident_id: int, client: OpenRouterClient | None = None,
                     force: bool = False) -> Action | None:
    lock_key = f"lock:analyze:{incident_id}"
    if not cache.acquire_lock(lock_key, ttl=180):
        logger.info("Incident #{} is already being analysed", incident_id)
        return None
    try:
        incident = incidents_repo.get(db, incident_id)
        if incident is None:
            logger.warning("Incident #{} not found", incident_id)
            return None
        if incident.actions and not force:
            logger.info("Incident #{} already analysed", incident_id)
            return None
        service = incident.service
        allowed = auto_actions_allowed(db, service)
        ctx = build_context(db, incident, service, allowed)

        use_llm = settings.openrouter_enabled and bool(settings_repo.get_value(db, "ai_enabled")) \
            and not service.is_test
        decision: AgentDecision | None = None
        conversation: AIConversation | None = None
        fallback_reason = "OpenRouter не настроен" if not settings.openrouter_enabled else (
            "ИИ отключён в настройках" if not use_llm else None)

        if use_llm:
            try:
                decision, exchange = ask_llm(ctx, client or OpenRouterClient.from_settings())
                conversation = _save_exchange(db, exchange, incident)
            except AgentError as exc:
                logger.warning("OpenRouter failed for incident #{}: {}", incident_id, exc)
                _save_exchange(db, exc.exchange, incident)
                fallback_reason = f"OpenRouter недоступен: {exc}"[:300]

        source = "openrouter"
        if decision is None:
            decision, exchange = fallback_decision(ctx, fallback_reason)
            conversation = _save_exchange(db, exchange, incident)
            source = "fallback"

        incident.problem_type = decision.problem_type
        incident.severity = decision.severity
        incident.ai_summary = decision.summary or decision.recommendation

        action = actions_repo.add(db, Action(
            incident_id=incident.id, service_id=service.id,
            conversation_id=conversation.id if conversation else None,
            source=source, problem_type=decision.problem_type,
            recommendation=decision.recommendation,
            command=decision.command.action,
            command_payload=decision.command.model_dump(),
            status=ActionStatus.suggested.value,
        ))
        audit_logger.info("AGENT incident=#{} service='{}' source={} type={} command={} auto_allowed={}",
                          incident.id, service.name, source, decision.problem_type,
                          decision.command.action, allowed)
        executor.apply_policy(db, action, service, allowed)
        db.commit()
        return action
    except Exception:
        db.rollback()
        logger.exception("Incident analysis failed for #{}", incident_id)
        raise
    finally:
        cache.release_lock(lock_key)
