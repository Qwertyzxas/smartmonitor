from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.core import cache
from app.models import utcnow
from app.repositories import actions as actions_repo
from app.repositories import checks as checks_repo
from app.repositories import incidents as incidents_repo
from app.repositories import services as services_repo
from app.repositories import test_runs as runs_repo
from app.schemas import ServiceWithStats, SummaryOut, TestRunOut

CACHE_TTL = 10


def services_with_stats(db: Session, use_cache: bool = True) -> list[ServiceWithStats]:
    if use_cache:
        cached = cache.get_json("stats:services")
        if cached is not None:
            return [ServiceWithStats.model_validate(item) for item in cached]

    start = utcnow() - timedelta(hours=24)
    aggregates = checks_repo.aggregates_since(db, start)
    open_map = incidents_repo.open_map(db)
    result: list[ServiceWithStats] = []
    for service in services_repo.list_all(db):
        item = ServiceWithStats.model_validate(service)
        agg = aggregates.get(service.id)
        if agg and agg.total:
            item.checks_24h = agg.total
            item.uptime_24h = round(agg.available / agg.total * 100, 2)
            item.avg_ms_24h = round(agg.avg_ms, 1) if agg.avg_ms is not None else None
        item.open_incident_id = open_map.get(service.id)
        last = checks_repo.recent(db, service.id, limit=1)
        item.last_duration_ms = last[0].duration_ms if last else None
        result.append(item)

    if use_cache:
        cache.set_json("stats:services", [r.model_dump(mode="json") for r in result], CACHE_TTL)
    return result


def summary(db: Session, use_cache: bool = True) -> SummaryOut:
    if use_cache:
        cached = cache.get_json("stats:summary")
        if cached is not None:
            return SummaryOut.model_validate(cached)

    services = services_with_stats(db, use_cache=use_cache)
    start = utcnow() - timedelta(hours=24)
    statuses = [s.current_status for s in services if s.is_active]
    total_checks = sum(s.checks_24h for s in services)
    weighted_uptime = sum((s.uptime_24h or 0) * s.checks_24h for s in services)
    weighted_ms = [(s.avg_ms_24h, s.checks_24h) for s in services if s.avg_ms_24h is not None]
    ms_weight = sum(w for _, w in weighted_ms)
    latest = runs_repo.latest(db)

    result = SummaryOut(
        services_total=len(services),
        services_active=sum(1 for s in services if s.is_active),
        up=statuses.count("up"),
        degraded=statuses.count("degraded"),
        down=statuses.count("down"),
        unknown=sum(1 for st in statuses if st is None),
        uptime_24h=round(weighted_uptime / total_checks, 2) if total_checks else None,
        avg_ms_24h=round(sum(m * w for m, w in weighted_ms) / ms_weight, 1) if ms_weight else None,
        checks_24h=total_checks,
        open_incidents=incidents_repo.count_open(db),
        incidents_24h=incidents_repo.count_since(db, start),
        actions_24h=actions_repo.count_since(db, start),
        last_test_run=TestRunOut.model_validate(latest) if latest else None,
    )
    if use_cache:
        cache.set_json("stats:summary", result.model_dump(mode="json"), CACHE_TTL)
    return result


def invalidate() -> None:
    cache.delete("stats:summary", "stats:services")
