from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from dev_agent.models import utcnow


class ResourceType(StrEnum):
    PROJECT = "project"
    COMPOSE_PROJECT = "compose_project"
    COMPOSE_SERVICE = "compose_service"
    CONTAINER = "container"
    IMAGE = "image"
    VOLUME = "volume"
    NETWORK = "network"
    PORT = "port"
    PROCESS = "process"
    DOCKERFILE = "dockerfile"
    COMPOSE_FILE = "compose_file"
    MAKEFILE = "makefile"
    MAKE_TARGET = "make_target"
    ENV_FILE = "env_file"
    RUNTIME = "runtime"


class RelationshipType(StrEnum):
    OWNS = "OWNS"
    BELONGS_TO = "BELONGS_TO"
    EXPOSES = "EXPOSES"
    FORWARDS_TO = "FORWARDS_TO"
    USES = "USES"
    MOUNTS = "MOUNTS"
    RUNS = "RUNS"
    BUILT_FROM = "BUILT_FROM"
    CONFIGURED_BY = "CONFIGURED_BY"
    STARTED_BY = "STARTED_BY"
    CONNECTED_TO = "CONNECTED_TO"
    DEPENDS_ON = "DEPENDS_ON"
    LISTENS_ON = "LISTENS_ON"
    CHILD_OF = "CHILD_OF"


class ResourceNode(BaseModel):
    id: str
    resource_type: ResourceType
    resource_id: str
    label: str
    status: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)


class ResourceEdge(BaseModel):
    source: str
    target: str
    relationship: RelationshipType
    attributes: dict[str, Any] = Field(default_factory=dict)


class TopologyGraph(BaseModel):
    nodes: list[ResourceNode] = Field(default_factory=list)
    edges: list[ResourceEdge] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utcnow)
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class ResourceInspection(BaseModel):
    node: ResourceNode
    relationships: list[ResourceEdge] = Field(default_factory=list)
    related: list[ResourceNode] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utcnow)
