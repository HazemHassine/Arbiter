from pydantic import BaseModel, Field


class RuntimeCapability(BaseModel):
    name: str
    available: bool
    support: str
    detail: str | None = None
    capabilities: list[str] = Field(default_factory=list)
