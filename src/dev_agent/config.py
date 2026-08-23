from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    dev_agent_host: str = "127.0.0.1"
    dev_agent_port: int = 8765
    database_url: str = "sqlite:///./dev_agent.db"
    project_roots: Annotated[list[Path], NoDecode] = Field(default_factory=list)
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_reasoning_effort: str | None = "none"
    agent_max_steps: int = 12
    auto_approve_read_only: bool = True
    auto_approve_low_risk: bool = False
    default_port_search_range_start: int = 3000
    default_port_search_range_end: int = 9999
    subprocess_timeout: float = 30.0

    @field_validator("project_roots", mode="before")
    @classmethod
    def parse_roots(cls, value: object) -> object:
        if isinstance(value, str):
            return [Path(item).expanduser() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
