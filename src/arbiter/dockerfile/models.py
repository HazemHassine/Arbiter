from pathlib import Path

from pydantic import BaseModel, Field


class DockerfileInstruction(BaseModel):
    keyword: str
    value: str
    line: int


class DockerfileStage(BaseModel):
    index: int
    base_image: str
    name: str | None = None
    instructions: list[DockerfileInstruction] = Field(default_factory=list)


class DockerfileInfo(BaseModel):
    path: Path
    stages: list[DockerfileStage] = Field(default_factory=list)
    workdir: str | None = None
    copy_instructions: list[str] = Field(default_factory=list)
    run: list[str] = Field(default_factory=list)
    args: dict[str, str | None] = Field(default_factory=dict)
    environment: dict[str, str | None] = Field(default_factory=dict)
    exposed_ports: list[str] = Field(default_factory=list)
    cmd: str | None = None
    entrypoint: str | None = None
    healthcheck: str | None = None
    user: str | None = None
    warnings: list[dict[str, str]] = Field(default_factory=list)
