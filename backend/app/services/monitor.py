"""HTTP probing of monitored services and evaluation of the result."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from statistics import mean

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from app.core import cache
from app.models import Check, CheckStatus, Service, utcnow
from app.repositories import checks as checks_repo
from app.services import incidents as incident_service

BODY_LIMIT = 2000
USER_AGENT = "SmartMonitor/1.0 (+uptime-checker)"
SPIKE_FACTOR = 3.0
SPIKE_MIN_MS = 500.0


@dataclass
class ProbeResult:
    status_code: int | None
    duration_ms: float | None
    error: str | None = None
    error_kind: str | None = None  # timeout | connection | dns | ssl | protocol
    body: str | None = None


@dataclass
class Evaluation:
    status: CheckStatus
    reason: str
    details: dict[str, float] = field(default_factory=dict)


@dataclass
class CheckOutcome:
    check: Check
    incident_opened_id: int | None = None
    incident_resolved_id: int | None = None


def probe(url: str, timeout: float, transport: httpx.BaseTransport | None = None) -> ProbeResult:
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, transport=transport,
                          headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(url)
        duration = (time.perf_counter() - started) * 1000
        return ProbeResult(response.status_code, round(duration, 2), body=response.text[:BODY_LIMIT])
    except httpx.TimeoutException as exc:
        return ProbeResult(None, round((time.perf_counter() - started) * 1000, 2),
                           f"Timeout after {timeout}s: {exc.__class__.__name__}", "timeout")
    except httpx.ConnectError as exc:
        msg = str(exc) or exc.__class__.__name__
        low = msg.lower()
        if "name or service not known" in low or "nodename nor servname" in low or "getaddrinfo" in low \
                or "name resolution" in low:
            kind = "dns"
        elif "ssl" in low or "certificate" in low:
            kind = "ssl"
        else:
            kind = "connection"
        return ProbeResult(None, round((time.perf_counter() - started) * 1000, 2), msg[:500], kind)
    except httpx.HTTPError as exc:
        return ProbeResult(None, round((time.perf_counter() - started) * 1000, 2),
                           (str(exc) or exc.__class__.__name__)[:500], "protocol")


def evaluate(result: ProbeResult, slow_threshold_ms: int, recent_durations: list[float]) -> Evaluation:
    """Classify a probe as up / degraded / down."""
    if result.error_kind:
        return Evaluation(CheckStatus.down, f"{result.error_kind}: {result.error}")
    code = result.status_code or 0
    if code >= 500:
        return Evaluation(CheckStatus.down, f"HTTP {code} (server error)")
    if code >= 400:
        return Evaluation(CheckStatus.down, f"HTTP {code} (client error)")

    duration = result.duration_ms or 0.0
    if duration > slow_threshold_ms:
        return Evaluation(CheckStatus.degraded,
                          f"Slow response: {duration:.0f} ms > threshold {slow_threshold_ms} ms",
                          {"duration_ms": duration})
    samples = [d for d in recent_durations if d is not None]
    if len(samples) >= 3:
        baseline = mean(samples)
        if duration > SPIKE_MIN_MS and duration > baseline * SPIKE_FACTOR:
            return Evaluation(CheckStatus.degraded,
                              f"Response time spike: {duration:.0f} ms vs baseline {baseline:.0f} ms",
                              {"duration_ms": duration, "baseline_ms": baseline})
    return Evaluation(CheckStatus.up, "OK")


def run_check(db: Session, service: Service, manual: bool = False,
              transport: httpx.BaseTransport | None = None) -> CheckOutcome:
    """Probe the service, persist a Check and drive incident lifecycle."""
    recent = checks_repo.recent(db, service.id, limit=10)
    baseline = [c.duration_ms for c in recent if c.status == CheckStatus.up.value and c.duration_ms]

    result = probe(service.url, service.timeout_seconds, transport=transport)
    evaluation = evaluate(result, service.slow_threshold_ms, baseline)

    check = checks_repo.add(db, Check(
        service_id=service.id,
        checked_at=utcnow(),
        status=evaluation.status.value,
        status_code=result.status_code,
        duration_ms=result.duration_ms,
        error=(result.error or (evaluation.reason if evaluation.status != CheckStatus.up else None)),
        error_kind=result.error_kind,
        response_body=result.body,
        manual=manual,
    ))
    service.current_status = evaluation.status.value
    service.last_checked_at = check.checked_at

    transition = incident_service.process_check(db, service, check, evaluation.reason)
    db.commit()

    logger.info("Check service={} status={} code={} {}ms", service.name, check.status,
                check.status_code, check.duration_ms)
    cache.delete("stats:summary", "stats:services")

    outcome = CheckOutcome(check=check)
    if transition.opened is not None:
        outcome.incident_opened_id = transition.opened.id
        incident_service.on_incident_opened(service, transition.opened)
    if transition.resolved is not None:
        outcome.incident_resolved_id = transition.resolved.id
        incident_service.on_incident_resolved(service, transition.resolved)
    return outcome
