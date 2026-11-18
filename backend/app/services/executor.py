"""Execution of structured agent commands (stubbed: audit log + optional webhook)."""
from __future__ import annotations

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import audit_logger
from app.models import DANGEROUS_COMMANDS, Action, ActionStatus, AgentCommand, Service, User, utcnow
from app.services import notifications


def apply_policy(db: Session, action: Action, service: Service, auto_allowed: bool) -> Action:
    """Decide what happens with a freshly suggested action.

    * ``none``          -> stored as an informational recommendation;
    * ``notify_admin``  -> safe, executed immediately;
    * ``restart`` / ``scale_up`` -> executed automatically only if the admin enabled
      auto-actions globally AND for this service, otherwise waits for manual approval.
    """
    if action.command == AgentCommand.none.value:
        action.status = ActionStatus.info.value
        action.result = "Команда не требуется"
        return action
    if action.command in DANGEROUS_COMMANDS and not auto_allowed:
        action.status = ActionStatus.suggested.value
        action.result = "Ожидает подтверждения администратора (авто-действия выключены)"
        return action
    return execute(db, action, service, user=None)


def execute(db: Session, action: Action, service: Service, user: User | None) -> Action:
    payload = {
        "action_id": action.id,
        "incident_id": action.incident_id,
        "service": {"id": service.id, "name": service.name, "url": service.url},
        "command": action.command,
        "params": (action.command_payload or {}).get("params", {}),
        "initiator": user.username if user else "ai-agent",
    }
    try:
        if action.command == AgentCommand.notify_admin.value:
            text = (f"🛎 <b>SmartMonitor</b>: агент просит внимания администратора\n"
                    f"Сервис: <b>{service.name}</b> ({service.url})\n"
                    f"Инцидент #{action.incident_id}\n{action.recommendation}")
            sent = False if service.is_test else notifications.send_message(text)
            result = "Уведомление отправлено в Telegram" if sent else \
                "Telegram не настроен — уведомление записано в журнал агента"
        else:
            result = f"[STUB] Команда '{action.command}' для '{service.name}' выполнена (имитация)"
            if settings.action_webhook_url:
                response = httpx.post(settings.action_webhook_url, json=payload, timeout=10)
                result += f"; webhook → HTTP {response.status_code}"
                response.raise_for_status()
        action.status = ActionStatus.executed.value
        action.result = result
        audit_logger.info("EXECUTED action=#{} command={} service='{}' by={} auto={}", action.id,
                          action.command, service.name, payload["initiator"], user is None)
    except Exception as exc:  # noqa: BLE001
        action.status = ActionStatus.failed.value
        action.result = f"Ошибка выполнения: {exc}"[:1000]
        logger.exception("Action #{} failed", action.id)
    action.auto = user is None
    action.executed_by_id = user.id if user else None
    action.executed_at = utcnow()
    db.flush()
    return action
