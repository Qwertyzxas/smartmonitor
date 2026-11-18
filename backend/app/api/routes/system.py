from __future__ import annotations

import asyncio
import random

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

from app.api.deps import DB, AdminUser, CurrentUser, Pagination
from app.core import cache
from app.core.config import settings
from app.core.database import engine
from app.repositories import conversations as conv_repo
from app.repositories import services as services_repo
from app.repositories import settings_repo
from app.repositories import test_runs as runs_repo
from app.repositories import users as users_repo
from app.schemas import (AppSettingsOut, AppSettingsUpdate, ConversationDetail, ConversationOut, Page,
                         ServiceOut, SimModeUpdate, SummaryOut, TestRunDetail, TestRunOut)
from app.services import jobs, notifications, simulator, stats

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health() -> dict[str, object]:
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "redis": cache.ping(),
            "openrouter": settings.openrouter_enabled, "telegram": settings.telegram_enabled}


@router.get("/stats/summary", response_model=SummaryOut)
def summary(db: DB, _: CurrentUser) -> SummaryOut:
    return stats.summary(db)


@router.get("/ai/conversations", response_model=Page[ConversationOut])
def conversations(db: DB, _: AdminUser, pg: Pagination, provider: str | None = None) -> Page[ConversationOut]:
    items, total = conv_repo.page(db, *pg, provider=provider)
    return Page[ConversationOut](items=[ConversationOut.model_validate(c) for c in items], total=total,
                                 page=pg[0], size=pg[1])


@router.get("/ai/conversations/{conversation_id}", response_model=ConversationDetail)
def conversation(conversation_id: int, db: DB, _: AdminUser) -> ConversationDetail:
    item = conv_repo.get(db, conversation_id)
    if item is None:
        raise HTTPException(404, "Conversation not found")
    return ConversationDetail.model_validate(item)


def _settings_out(db: DB) -> AppSettingsOut:
    rows = settings_repo.get_all(db)
    latest = max(rows.values(), key=lambda r: r.updated_at, default=None)
    updated_by = None
    if latest is not None and latest.updated_by_id:
        user = users_repo.get(db, latest.updated_by_id)
        updated_by = user.username if user else None
    return AppSettingsOut(
        auto_actions_enabled=bool(settings_repo.get_value(db, "auto_actions_enabled")),
        ai_enabled=bool(settings_repo.get_value(db, "ai_enabled")),
        telegram_notifications=bool(settings_repo.get_value(db, "telegram_notifications")),
        openrouter_configured=settings.openrouter_enabled,
        openrouter_model=settings.openrouter_model,
        telegram_configured=settings.telegram_enabled,
        updated_by=updated_by,
        updated_at=latest.updated_at if latest else None,
    )


@router.get("/settings", response_model=AppSettingsOut)
def get_settings(db: DB, _: CurrentUser) -> AppSettingsOut:
    return _settings_out(db)


@router.put("/settings", response_model=AppSettingsOut)
def update_settings(body: AppSettingsUpdate, db: DB, admin: AdminUser) -> AppSettingsOut:
    for key, value in body.model_dump(exclude_none=True).items():
        settings_repo.set_value(db, key, value, admin.id)
    db.commit()
    return _settings_out(db)


@router.get("/qa/runs", response_model=Page[TestRunOut])
def test_runs(db: DB, _: CurrentUser, pg: Pagination) -> Page[TestRunOut]:
    items, total = runs_repo.page(db, *pg)
    return Page[TestRunOut](items=[TestRunOut.model_validate(r) for r in items], total=total,
                            page=pg[0], size=pg[1])


@router.get("/qa/runs/{run_id}", response_model=TestRunDetail)
def test_run(run_id: int, db: DB, _: CurrentUser) -> TestRunDetail:
    run = runs_repo.get(db, run_id)
    if run is None:
        raise HTTPException(404, "Test run not found")
    return TestRunDetail.model_validate(run)


@router.post("/qa/runs", status_code=202)
def trigger_tests(_: AdminUser) -> dict[str, str]:
    return {"status": "queued", "via": jobs.enqueue_test_run("manual")}


@router.post("/reports/telegram")
def send_report(_: AdminUser) -> dict[str, object]:
    if not settings.telegram_enabled:
        raise HTTPException(400, "Telegram не настроен (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
    return {"sent": notifications.send_report()}


@router.get("/reports/preview", response_class=PlainTextResponse)
def preview_report(db: DB, _: AdminUser) -> str:
    return notifications.build_report(db)


@router.get("/sim", response_model=dict[str, str])
def sim_list(_: AdminUser) -> dict[str, str]:
    return simulator.list_modes()


@router.put("/sim/{name}")
def sim_set(name: str, body: SimModeUpdate, _: AdminUser) -> dict[str, str]:
    simulator.set_mode(name, body.mode)
    return {"name": name, "mode": body.mode}


@router.post("/sim/{name}/service", response_model=ServiceOut, status_code=201)
def sim_create_service(name: str, db: DB, _: AdminUser) -> ServiceOut:
    if not name.replace("-", "").isalnum():
        raise HTTPException(400, "Имя может содержать только латиницу, цифры и дефис")
    simulator.set_mode(name, "up")
    service = services_repo.create(
        db, name=f"Симулятор: {name}", url=f"{settings.backend_internal_url.rstrip('/')}/api/sim/{name}",
        interval_seconds=20, timeout_seconds=5, slow_threshold_ms=1500)
    db.commit()
    stats.invalidate()
    return ServiceOut.model_validate(service)


@router.get("/sim/{name}", include_in_schema=True)
async def sim_endpoint(name: str) -> JSONResponse:
    mode = simulator.get_mode(name)
    if mode == "flaky":
        mode = random.choice(["up", "down"])
    if mode == "down":
        return JSONResponse({"error": "Service Unavailable"}, status_code=503)
    if mode == "db_error":
        return JSONResponse({"error": "Internal Server Error",
                             "detail": "database error: connection pool exhausted, could not connect "
                                       "to postgres (too many connections)"}, status_code=500)
    if mode == "slow":
        await asyncio.sleep(2.5)
    if mode == "timeout":
        await asyncio.sleep(30)
    return JSONResponse({"status": "ok", "service": name, "mode": mode})
