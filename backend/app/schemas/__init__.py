from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_validator("*", mode="after")
    @classmethod
    def _aware_datetimes(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.\-]+$")
    password: str = Field(min_length=6, max_length=128)


class UserOut(ORMModel):
    id: int
    username: str
    role: str
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserRoleUpdate(BaseModel):
    role: Literal["admin", "viewer"]


class ServiceBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: HttpUrl
    interval_seconds: int = Field(60, ge=10, le=86400)
    timeout_seconds: float = Field(10.0, gt=0, le=60)
    slow_threshold_ms: int = Field(2000, ge=50, le=60000)
    is_active: bool = True
    auto_actions_enabled: bool = False


class ServiceCreate(ServiceBase):
    is_test: bool = False


class ServiceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    url: HttpUrl | None = None
    interval_seconds: int | None = Field(None, ge=10, le=86400)
    timeout_seconds: float | None = Field(None, gt=0, le=60)
    slow_threshold_ms: int | None = Field(None, ge=50, le=60000)
    is_active: bool | None = None
    auto_actions_enabled: bool | None = None


class ServiceOut(ORMModel):
    id: int
    name: str
    url: str
    interval_seconds: int
    timeout_seconds: float
    slow_threshold_ms: int
    is_active: bool
    auto_actions_enabled: bool
    is_test: bool
    current_status: str | None
    last_checked_at: datetime | None
    created_at: datetime


class ServiceWithStats(ServiceOut):
    uptime_24h: float | None = None
    avg_ms_24h: float | None = None
    checks_24h: int = 0
    open_incident_id: int | None = None
    last_duration_ms: float | None = None


class CheckOut(ORMModel):
    id: int
    service_id: int
    checked_at: datetime
    status: str
    status_code: int | None
    duration_ms: float | None
    error: str | None
    error_kind: str | None
    response_body: str | None
    manual: bool


class CheckRequest(BaseModel):
    service_id: int


class CheckResultOut(BaseModel):
    check: CheckOut
    incident_opened: int | None = None
    incident_resolved: int | None = None


class TimePoint(ORMModel):
    t: datetime
    ms: float | None
    status: str
    code: int | None


class ActionOut(ORMModel):
    id: int
    incident_id: int
    service_id: int
    conversation_id: int | None
    source: str
    problem_type: str | None
    recommendation: str
    command: str
    command_payload: dict[str, Any] | None
    status: str
    auto: bool
    result: str | None
    executed_by_id: int | None
    created_at: datetime
    executed_at: datetime | None


class IncidentOut(ORMModel):
    id: int
    service_id: int
    status: str
    started_at: datetime
    resolved_at: datetime | None
    reason: str
    problem_type: str | None
    severity: str | None
    ai_summary: str | None
    failed_checks: int
    service_name: str | None = None


class IncidentDetail(IncidentOut):
    actions: list[ActionOut] = []
    recent_checks: list[CheckOut] = []


class ConversationOut(ORMModel):
    id: int
    incident_id: int | None
    service_id: int | None
    provider: str
    model: str
    success: bool
    error: str | None
    latency_ms: float | None
    created_at: datetime
    parsed: dict[str, Any] | None


class ConversationDetail(ConversationOut):
    request: dict[str, Any]
    response: str | None


class AgentCommandModel(BaseModel):
    action: Literal["restart", "scale_up", "notify_admin", "none"] = "none"
    target: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None

    @field_validator("action", mode="before")
    @classmethod
    def _normalise_action(cls, v: Any) -> str:
        v = str(v or "none").strip().lower()
        return v if v in {"restart", "scale_up", "notify_admin", "none"} else "none"


class AgentDecision(BaseModel):
    problem_type: Literal["network", "server", "database", "performance", "unknown"] = "unknown"
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    summary: str = ""
    recommendation: str
    command: AgentCommandModel = Field(default_factory=AgentCommandModel)

    @field_validator("problem_type", mode="before")
    @classmethod
    def _normalise_type(cls, v: Any) -> str:
        v = str(v or "unknown").strip().lower()
        return v if v in {"network", "server", "database", "performance", "unknown"} else "unknown"

    @field_validator("severity", mode="before")
    @classmethod
    def _normalise_severity(cls, v: Any) -> str:
        v = str(v or "medium").strip().lower()
        return v if v in {"low", "medium", "high", "critical"} else "medium"


class AppSettingsOut(ORMModel):
    auto_actions_enabled: bool
    ai_enabled: bool
    telegram_notifications: bool
    openrouter_configured: bool
    openrouter_model: str
    telegram_configured: bool
    updated_by: str | None = None
    updated_at: datetime | None = None


class AppSettingsUpdate(BaseModel):
    auto_actions_enabled: bool | None = None
    ai_enabled: bool | None = None
    telegram_notifications: bool | None = None


class TestRunOut(ORMModel):
    __test__ = False

    id: int
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_s: float | None
    total: int
    passed: int
    failed: int
    skipped: int
    errors: int


class TestRunDetail(TestRunOut):
    cases: list[Any]
    output: str | None


class SummaryOut(BaseModel):
    services_total: int
    services_active: int
    up: int
    degraded: int
    down: int
    unknown: int
    uptime_24h: float | None
    avg_ms_24h: float | None
    checks_24h: int
    open_incidents: int
    incidents_24h: int
    actions_24h: int
    last_test_run: TestRunOut | None = None


class SimModeUpdate(BaseModel):
    mode: Literal["up", "down", "slow", "db_error", "timeout", "flaky"]
