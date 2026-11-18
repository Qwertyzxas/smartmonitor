from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import DB, AdminUser, CurrentUser, Pagination
from app.models import ActionStatus, AgentCommand, Incident, IncidentStatus
from app.repositories import actions as actions_repo
from app.repositories import checks as checks_repo
from app.repositories import conversations as conv_repo
from app.repositories import incidents as incidents_repo
from app.schemas import ActionOut, CheckOut, ConversationOut, IncidentDetail, IncidentOut, Page
from app.services import ai_agent, executor, stats
from app.services import incidents as incident_service

router = APIRouter(prefix="/api", tags=["incidents"])


def _to_out(incident: Incident) -> IncidentOut:
    dto = IncidentOut.model_validate(incident)
    dto.service_name = incident.service.name if incident.service else None
    return dto


def _get_or_404(db: DB, incident_id: int) -> Incident:
    incident = incidents_repo.get(db, incident_id)
    if incident is None:
        raise HTTPException(404, "Incident not found")
    return incident


@router.get("/incidents", response_model=Page[IncidentOut])
def list_incidents(db: DB, _: CurrentUser, pg: Pagination, status: str | None = None) -> Page[IncidentOut]:
    items, total = incidents_repo.page(db, *pg, status=status)
    return Page[IncidentOut](items=[_to_out(i) for i in items], total=total, page=pg[0], size=pg[1])


@router.get("/incidents/{incident_id}", response_model=IncidentDetail)
def get_incident(incident_id: int, db: DB, _: CurrentUser) -> IncidentDetail:
    incident = _get_or_404(db, incident_id)
    detail = IncidentDetail.model_validate(incident)
    detail.service_name = incident.service.name
    detail.actions = [ActionOut.model_validate(a) for a in actions_repo.for_incident(db, incident_id)]
    detail.recent_checks = [CheckOut.model_validate(c) for c in checks_repo.recent(db, incident.service_id, 10)]
    return detail


@router.get("/incidents/{incident_id}/conversations", response_model=list[ConversationOut])
def incident_conversations(incident_id: int, db: DB, _: AdminUser) -> list[ConversationOut]:
    return [ConversationOut.model_validate(c) for c in conv_repo.for_incident(db, incident_id)]


@router.post("/incidents/{incident_id}/analyze")
def reanalyze(incident_id: int, db: DB, _: AdminUser) -> dict[str, object]:
    _get_or_404(db, incident_id)
    action = ai_agent.analyze_incident(db, incident_id, force=True)
    return {"status": "done" if action else "busy", "action_id": action.id if action else None}


@router.post("/incidents/{incident_id}/resolve", response_model=IncidentOut)
def resolve(incident_id: int, db: DB, _: AdminUser) -> IncidentOut:
    incident = _get_or_404(db, incident_id)
    if incident.status == IncidentStatus.open.value:
        incident_service.resolve(incident)
        db.commit()
        stats.invalidate()
    return _to_out(incident)


@router.get("/actions", response_model=Page[ActionOut])
def list_actions(db: DB, _: CurrentUser, pg: Pagination, status: str | None = None) -> Page[ActionOut]:
    items, total = actions_repo.page(db, *pg, status=status)
    return Page[ActionOut](items=[ActionOut.model_validate(a) for a in items], total=total, page=pg[0], size=pg[1])


@router.post("/actions/{action_id}/execute", response_model=ActionOut)
def execute_action(action_id: int, db: DB, admin: AdminUser) -> ActionOut:
    action = actions_repo.get(db, action_id)
    if action is None:
        raise HTTPException(404, "Action not found")
    if action.status not in (ActionStatus.suggested.value, ActionStatus.failed.value):
        raise HTTPException(409, f"Action is already {action.status}")
    if action.command == AgentCommand.none.value:
        raise HTTPException(400, "Action has no command")
    executor.execute(db, action, action.incident.service, user=admin)
    db.commit()
    return ActionOut.model_validate(action)


@router.post("/actions/{action_id}/reject", response_model=ActionOut)
def reject_action(action_id: int, db: DB, admin: AdminUser) -> ActionOut:
    action = actions_repo.get(db, action_id)
    if action is None:
        raise HTTPException(404, "Action not found")
    if action.status != ActionStatus.suggested.value:
        raise HTTPException(409, f"Action is already {action.status}")
    action.status = ActionStatus.skipped.value
    action.result = f"Отклонено администратором {admin.username}"
    action.executed_by_id = admin.id
    db.commit()
    return ActionOut.model_validate(action)
