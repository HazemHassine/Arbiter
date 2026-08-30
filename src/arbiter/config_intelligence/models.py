from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class PortDriftType(StrEnum):
    COMPOSE_DEFAULT_MISMATCH = "compose_default_mismatch"
    EXAMPLE_MISMATCH = "example_mismatch"
    UNRESOLVED_COMPOSE_VARIABLE = "unresolved_compose_variable"
    UNREFERENCED_ENV_PORT = "unreferenced_env_port"
    RUNTIME_PORT_COLLISION = "runtime_port_collision"


class PortDriftItem(BaseModel):
    service: str | None = None
    variable: str | None = None
    env_value: int | None = None
    compose_default: int | None = None
    example_value: int | None = None
    compose_mapping: str | None = None
    drift_type: PortDriftType
    severity: str = "warning"  # "info", "warning", "critical"
    message: str
    suggested_fix: str | None = None


class EnvVarAuditStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"
    EMPTY = "empty"
    PLACEHOLDER = "placeholder"
    UNDOCUMENTED = "undocumented"


class EnvVarAuditItem(BaseModel):
    key: str
    status: EnvVarAuditStatus
    is_secret: bool = False
    masked_value: str | None = None
    example_preview: str | None = None
    comment: str | None = None
    recommendation: str | None = None


class ProjectConfigDrift(BaseModel):
    project_id: str
    project_name: str
    project_path: str
    has_env: bool
    has_env_example: bool
    has_compose: bool
    drift_score: int = 0
    status: str = "clean"  # "clean", "warning", "critical"
    port_drifts: list[PortDriftItem] = Field(default_factory=list)
    missing_env_vars: list[EnvVarAuditItem] = Field(default_factory=list)
    env_audit: list[EnvVarAuditItem] = Field(default_factory=list)
    summary: str
    recommendations: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utcnow)


class VisualDiffLine(BaseModel):
    line_number_before: int | None = None
    line_number_after: int | None = None
    kind: str = "unchanged"  # "unchanged", "addition", "deletion"
    content: str


class VisualDiff(BaseModel):
    file_path: str
    unified_diff: str
    lines: list[VisualDiffLine] = Field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    is_secret_file: bool = False


class StateTransition(BaseModel):
    resource_type: str
    identifier: str
    label: str
    before_state: dict[str, Any] = Field(default_factory=dict)
    after_state: dict[str, Any] = Field(default_factory=dict)
    action_type: str = "state_transition"


class TimeTravelPreview(BaseModel):
    action: str
    summary: str
    visual_diffs: list[VisualDiff] = Field(default_factory=list)
    state_transitions: list[StateTransition] = Field(default_factory=list)
    port_changes: list[dict[str, Any]] = Field(default_factory=list)
    container_changes: list[dict[str, Any]] = Field(default_factory=list)
    impacted_dependencies: list[str] = Field(default_factory=list)
    resolves_drifts: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utcnow)
