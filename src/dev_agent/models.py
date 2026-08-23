from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


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


class Project(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    path: Path
    compose_files: list[Path] = Field(default_factory=list)
    has_makefile: bool = False
    has_env: bool = False
    has_dockerfile: bool = False
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
    mounts: list[dict[str, Any]] = Field(default_factory=list)
    networks: list[str] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    compose_project: str | None = None
    compose_service: str | None = None
    compose_working_dir: str | None = None


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
