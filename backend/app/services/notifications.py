from __future__ import annotations

from datetime import timedelta

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models import Incident, Service, TestRun, utcnow
from app.repositories import settings_repo


def _notifications_enabled() -> bool:
    if not settings.telegram_enabled:
        return False
    try:
        with SessionLocal() as db:
            return bool(settings_repo.get_value(db, "telegram_notifications"))
    except Exception:
        return True


def send_message(text: str, force: bool = False) -> bool:
    if not settings.telegram_enabled:
        logger.info("Telegram is not configured, message skipped: {}", text[:120].replace("\n", " "))
        return False
    if not force and not _notifications_enabled():
        return False
    try:
        response = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": settings.telegram_chat_id, "text": text[:4000], "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=10,
        )
        if response.status_code != 200:
            logger.warning("Telegram API error {}: {}", response.status_code, response.text[:200])
            return False
        return True
    except httpx.HTTPError as exc:
        logger.warning("Telegram send failed: {}", exc)
        return False


def notify_incident_opened(service: Service, incident: Incident) -> None:
    send_message(f"🔴 <b>Инцидент #{incident.id}</b>\nСервис: <b>{service.name}</b>\n{service.url}\n"
                 f"Причина: {incident.reason}")


def notify_incident_resolved(service: Service, incident: Incident) -> None:
    send_message(f"🟢 <b>Инцидент #{incident.id} закрыт</b>\nСервис <b>{service.name}</b> снова доступен.")


def notify_test_run(run: TestRun) -> None:
    icon = "✅" if run.status == "passed" else "❌"
    lines = [f"{icon} <b>Автотесты SmartMonitor</b>: {run.status}",
             f"Всего {run.total}, ✔ {run.passed}, ✖ {run.failed + run.errors}, ⏭ {run.skipped}, "
             f"{(run.duration_s or 0):.1f} с"]
    failed = [c for c in (run.cases or []) if c.get("outcome") in ("failed", "error")]
    for case in failed[:5]:
        lines.append(f"• {case.get('name')}: {(case.get('message') or '')[:120]}")
    send_message("\n".join(lines))


def build_report(db: Session) -> str:
    from app.services import stats

    summary = stats.summary(db, use_cache=False)
    services = stats.services_with_stats(db, use_cache=False)
    since = (utcnow() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M UTC")
    icons = {"up": "🟢", "degraded": "🟡", "down": "🔴"}
    lines = [f"📊 <b>SmartMonitor — отчёт за 24 ч</b> (с {since})",
             f"Сервисов: {summary.services_total} (активных {summary.services_active})",
             f"Доступность: {summary.uptime_24h if summary.uptime_24h is not None else '—'}%",
             f"Среднее время ответа: {round(summary.avg_ms_24h) if summary.avg_ms_24h else '—'} мс",
             f"Инцидентов: {summary.incidents_24h} (открыто сейчас {summary.open_incidents})",
             f"Действий ИИ-агента: {summary.actions_24h}", ""]
    for s in services:
        uptime = f"{s.uptime_24h}%" if s.uptime_24h is not None else "нет данных"
        lines.append(f"{icons.get(s.current_status or '', '⚪')} {s.name}: {uptime}")
    if summary.last_test_run:
        r = summary.last_test_run
        lines += ["", f"🧪 Последний прогон автотестов: {r.status} ({r.passed}/{r.total})"]
    return "\n".join(lines)


def send_report() -> bool:
    with SessionLocal() as db:
        text = build_report(db)
    return send_message(text, force=True)
