from pydantic import BaseModel, Field

from dev_agent.models import Risk


class MakeTargetInfo(BaseModel):
    name: str
    dependencies: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    description: str | None = None
    risk: Risk
    ports: list[int] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    starts_long_running_process: bool = False
