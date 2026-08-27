import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _default_state_directory() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base.expanduser() / "arbiter"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    arbiter_host: str = Field(
        default="127.0.0.1", validation_alias=AliasChoices("ARBITER_HOST", "DEV_AGENT_HOST")
    )
    arbiter_port: int = Field(default=8765, validation_alias=AliasChoices("ARBITER_PORT", "DEV_AGENT_PORT"))
    arbiter_trusted_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "::1"]
    )
    allow_remote_access: bool = False
    arbiter_state_directory: Path = Field(default_factory=_default_state_directory)
    database_url: str = "sqlite:///./arbiter.db"
    project_roots: Annotated[list[Path], NoDecode] = Field(default_factory=list)
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_reasoning_effort: str | None = "none"
    filter_llm_model: str = "gpt-5.4-nano"
    agent_max_steps: int = 12
    project_scan_depth: int = Field(default=4, ge=1, le=8)
    auto_approve_read_only: bool = True
    auto_approve_low_risk: bool = False
    default_port_search_range_start: int = 3000
    default_port_search_range_end: int = 9999
    subprocess_timeout: float = 30.0
    observation_interval_seconds: float = 3.0

    @field_validator("project_roots", mode="before")
    @classmethod
    def parse_roots(cls, value: object) -> object:
        if isinstance(value, str):
            return [Path(item).expanduser() for item in value.split(",") if item.strip()]
        return value

    @field_validator("arbiter_trusted_hosts", mode="before")
    @classmethod
    def parse_trusted_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            value = [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, (list, tuple)):
            normalized = [str(item).strip().lower().rstrip(".") for item in value if str(item).strip()]
            if not normalized:
                raise ValueError("ARBITER_TRUSTED_HOSTS must contain at least one host")
            if any("*" in item for item in normalized):
                raise ValueError("ARBITER_TRUSTED_HOSTS does not allow wildcards")
            return normalized
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
