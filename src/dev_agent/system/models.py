from typing import Any

from pydantic import BaseModel, Field


class ProcessInfo(BaseModel):
    pid: int
    ppid: int | None = None
    process: str | None = None
    command: str | None = None
    executable: str | None = None
    cwd: str | None = None
    uid: int | None = None
    state: str | None = None
    memory_bytes: int | None = None
    cpu_ticks: int | None = None
    cpu_seconds: float | None = None
    ports: list[int] = Field(default_factory=list)
    children: list[int] = Field(default_factory=list)
    container_id: str | None = None
    kind: str = "process"
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    project_path: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
