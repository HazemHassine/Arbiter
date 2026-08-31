from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


class Risk(StrEnum):
    READ_ONLY = "READ_ONLY"
    LOW_RISK = "LOW_RISK"
    MEDIUM_RISK = "MEDIUM_RISK"
    HIGH_RISK = "HIGH_RISK"
    DESTRUCTIVE = "DESTRUCTIVE"


class PortBinding(BaseModel):
    host_port: int
    container_port: int | None = None
    protocol: str = "tcp"
    host_ip: str | None = None
    service: str | None = None
    source: str | None = None
    variable: str | None = None


class PortOwner(BaseModel):
    port: int
    protocol: str = "tcp"
    state: str = "LISTEN"
    host: str | None = None
    owner_type: str = "unknown"
    pid: int | None = None
    process: str | None = None
    command: str | None = None
    container_id: str | None = None
    container: str | None = None
    project: str | None = None
    service: str | None = None
    source: str | None = None


class PortConflictReason(StrEnum):
    DECLARED_BY_ANOTHER_PROJECT = "declared_by_another_project"
    DUPLICATE_IN_PROJECT = "duplicate_in_project"
    OCCUPIED_AT_RUNTIME = "occupied_at_runtime"


class PortClaim(BaseModel):
    project: str
    project_id: str
    service: str = "unknown"
    source: str = "unknown"


class PortReconciliationChange(BaseModel):
    service: str | None = None
    requested_port: int
    protocol: str = "tcp"
    suggested_port: int
    source: str | None = None
    env_variable: str | None = None
    reasons: list[PortConflictReason] = Field(default_factory=list)
    conflicting_claims: list[PortClaim] = Field(default_factory=list)
    runtime_owner: PortOwner | None = None


class PortReconciliationPlan(BaseModel):
    project: str
    project_id: str
    status: str
    changes: list[PortReconciliationChange] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utcnow)


class Project(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    path: Path
    compose_files: list[Path] = Field(default_factory=list)
    has_makefile: bool = False
    has_env: bool = False
    has_dockerfile: bool = False
    dockerfiles: list[Path] = Field(default_factory=list)
    ports: list[PortBinding] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    status: str = "discovered"
    last_discovered: datetime = Field(default_factory=utcnow)


class ContainerInfo(BaseModel):
    id: str
    name: str
    image: str
    state: str
    status: str | None = None
    health: str | None = None
    restart_count: int = 0
    ports: list[PortBinding] = Field(default_factory=list)
    exposed_ports: list[PortBinding] = Field(default_factory=list)
    mounts: list[dict[str, Any]] = Field(default_factory=list)
    networks: list[str] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    compose_project: str | None = None
    compose_service: str | None = None
    compose_working_dir: str | None = None
    created: str | None = None
    command: list[str] = Field(default_factory=list)


class ActionSpec(BaseModel):
    action: str
    arguments: dict[str, Any]
    summary: str
    risk: Risk
    project_id: str | None = None
    request_id: str = Field(default_factory=lambda: str(uuid4()))


class ApprovalInfo(BaseModel):
    id: str
    request_id: str
    risk: Risk
    action: str
    summary: str
    arguments: dict[str, Any]
    status: str
    expires_at: datetime
    created_at: datetime


class ActionResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    action: str
    status: str
    result: dict[str, Any] = Field(default_factory=dict)
    verification: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ReadinessProbeType(StrEnum):
    TCP_PORT = "tcp_port"
    HTTP_GET = "http_get"
    DOCKER_HEALTH = "docker_health"


class ReadinessPolicyStatus(StrEnum):
    ALLOWED = "allowed"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED = "blocked"


class ReadinessGate(BaseModel):
    probe_type: ReadinessProbeType = ReadinessProbeType.TCP_PORT
    host: str = "127.0.0.1"
    port: int | None = Field(default=None, ge=1, le=65535)
    path: str | None = None
    timeout_seconds: float = Field(default=10.0, gt=0, le=30)
    retry_interval_seconds: float = Field(default=0.5, gt=0, le=10)
    expected_status: int = Field(default=200, ge=100, le=599)
    service: str | None = None

    @field_validator("host")
    @classmethod
    def safe_host(cls, value: str) -> str:
        normalized = value.strip().rstrip(".")
        if not normalized or any(char in normalized for char in "\r\n/@?#"):
            raise ValueError("Readiness host must be a plain hostname or IP address")
        return normalized

    @field_validator("path")
    @classmethod
    def safe_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if any(char in value for char in "\r\n"):
            raise ValueError("Readiness path contains invalid control characters")
        return value if value.startswith("/") else f"/{value}"


class ReadinessProbeResult(BaseModel):
    service: str | None = None
    probe_type: ReadinessProbeType
    target: str
    healthy: bool
    latency_ms: float = 0.0
    status_code: int | None = None
    message: str | None = None
    policy_status: ReadinessPolicyStatus = ReadinessPolicyStatus.ALLOWED
    policy_reason: str | None = None
    resolved_addresses: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=utcnow)


class ReadinessAuthorization(BaseModel):
    id: str
    target_key: str
    protocol: str
    host: str
    port: int
    resolved_addresses: list[str] = Field(default_factory=list)
    approval_id: str
    created_at: datetime


class StackProjectMember(BaseModel):
    project_id: str
    project_name: str
    env_overrides: dict[str, str] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    readiness_gates: list[ReadinessGate] = Field(default_factory=list)
    boot_stage: int = 0


class Stack(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str | None = None
    projects: list[StackProjectMember] = Field(default_factory=list)
    is_active: bool = False
    status: str = "inactive"
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class BootOrderStage(BaseModel):
    stage: int
    projects: list[str]
    readiness_gates: list[ReadinessGate] = Field(default_factory=list)
    description: str | None = None


class StackBootPlan(BaseModel):
    stack_id: str
    stack_name: str
    stages: list[BootOrderStage] = Field(default_factory=list)
    total_stages: int = 0
    dependencies_valid: bool = True
    cycle_detected: bool = False
    error: str | None = None


class StackSwitchResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    previous_stack_id: str | None = None
    target_stack_id: str
    stopped_projects: list[str] = Field(default_factory=list)
    started_projects: list[str] = Field(default_factory=list)
    port_reconciliations: list[PortReconciliationChange] = Field(default_factory=list)
    env_changes: list[dict[str, Any]] = Field(default_factory=list)
    readiness_results: list[ReadinessProbeResult] = Field(default_factory=list)
    status: str = "completed"
    verified: bool = True
    error: str | None = None
