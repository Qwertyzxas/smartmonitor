from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query, Response
from loguru import logger

from app.api.deps import DB, AdminUser, CurrentUser, Pagination
from app.models import Service, utcnow
from app.repositories import checks as checks_repo
from app.repositories import incidents as incidents_repo
from app.repositories import services as services_repo
from app.schemas import (CheckOut, CheckRequest, CheckResultOut, IncidentOut, Page, ServiceCreate,
                         ServiceOut, ServiceUpdate, ServiceWithStats, TimePoint)
from app.services import monitor, stats

router = APIRouter(prefix="/api", tags=["services"])


def _get_or_404(db: DB, service_id: int) -> Service:
    service = services_repo.get(db, service_id)
    if service is None:
        raise HTTPException(404, "Service not found")
    return service


@router.get("/services", response_model=list[ServiceWithStats])
def list_services(db: DB, _: CurrentUser) -> list[ServiceWithStats]:
    return stats.services_with_stats(db)


@router.post("/services", response_model=ServiceOut, status_code=201)
def create_service(body: ServiceCreate, db: DB, admin: AdminUser) -> ServiceOut:
    data = body.model_dump()
    data["url"] = str(body.url)
    service = services_repo.create(db, **data)
    db.commit()
    stats.invalidate()
    logger.info("Admin '{}' created service '{}' ({})", admin.username, service.name, service.url)
    return ServiceOut.model_validate(service)


@router.get("/services/{service_id}", response_model=ServiceWithStats)
def get_service(service_id: int, db: DB, _: CurrentUser) -> ServiceWithStats:
    _get_or_404(db, service_id)
    for item in stats.services_with_stats(db, use_cache=False):
        if item.id == service_id:
            return item
    service = _get_or_404(db, service_id)  # test services are hidden from the list
    return ServiceWithStats.model_validate(service)


@router.put("/services/{service_id}", response_model=ServiceOut)
def update_service(service_id: int, body: ServiceUpdate, db: DB, admin: AdminUser) -> ServiceOut:
    service = _get_or_404(db, service_id)
    data = body.model_dump(exclude_unset=True)
    if "url" in data and data["url"] is not None:
        data["url"] = str(data["url"])
    services_repo.update(db, service, **{k: v for k, v in data.items() if v is not None})
    db.commit()
    stats.invalidate()
    logger.info("Admin '{}' updated service #{}: {}", admin.username, service.id, list(data))
    return ServiceOut.model_validate(service)


@router.delete("/services/{service_id}", status_code=204, response_class=Response)
def delete_service(service_id: int, db: DB, admin: AdminUser) -> Response:
    service = _get_or_404(db, service_id)
    services_repo.delete(db, service)
    db.commit()
    stats.invalidate()
    logger.info("Admin '{}' deleted service #{}", admin.username, service_id)
    return Response(status_code=204)


@router.post("/services/{service_id}/check", response_model=CheckResultOut)
def run_manual_check(service_id: int, db: DB, _: AdminUser) -> CheckResultOut:
    service = _get_or_404(db, service_id)
    outcome = monitor.run_check(db, service, manual=True)
    return CheckResultOut(check=CheckOut.model_validate(outcome.check),
                          incident_opened=outcome.incident_opened_id,
                          incident_resolved=outcome.incident_resolved_id)


@router.post("/checks", response_model=CheckResultOut)
def create_check(body: CheckRequest, db: DB, admin: AdminUser) -> CheckResultOut:
    return run_manual_check(body.service_id, db, admin)


@router.get("/services/{service_id}/checks", response_model=Page[CheckOut])
def list_checks(service_id: int, db: DB, _: CurrentUser, pg: Pagination) -> Page[CheckOut]:
    _get_or_404(db, service_id)
    items, total = checks_repo.page(db, service_id, *pg)
    return Page[CheckOut](items=[CheckOut.model_validate(c) for c in items], total=total, page=pg[0], size=pg[1])


@router.get("/services/{service_id}/timeseries", response_model=list[TimePoint])
def timeseries(service_id: int, db: DB, _: CurrentUser,
               hours: int = Query(24, ge=1, le=168)) -> list[TimePoint]:
    _get_or_404(db, service_id)
    checks = checks_repo.since(db, service_id, utcnow() - timedelta(hours=hours))
    return [TimePoint(t=c.checked_at, ms=c.duration_ms, status=c.status, code=c.status_code) for c in checks]


@router.get("/services/{service_id}/incidents", response_model=Page[IncidentOut])
def service_incidents(service_id: int, db: DB, _: CurrentUser, pg: Pagination) -> Page[IncidentOut]:
    service = _get_or_404(db, service_id)
    items, total = incidents_repo.page(db, *pg, service_id=service_id)
    out = []
    for inc in items:
        dto = IncidentOut.model_validate(inc)
        dto.service_name = service.name
        out.append(dto)
    return Page[IncidentOut](items=out, total=total, page=pg[0], size=pg[1])
