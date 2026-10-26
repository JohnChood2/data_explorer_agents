"""Load hosts, ports, and database URLs from config.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


class ServiceConfig(BaseModel):
    """Where one app listens, and the database address it can call."""

    model_config = ConfigDict(extra="forbid")

    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    database_url: str = Field(min_length=1)

    @field_validator("host")
    @classmethod
    def strip_host(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("host must not be blank")
        return stripped

    @field_validator("database_url")
    @classmethod
    def strip_database_url(cls, value: str) -> str:
        stripped = value.strip().rstrip("/")
        if not stripped:
            raise ValueError("database_url must not be blank")
        return stripped

    @property
    def url(self) -> str:
        """HTTP origin for this app, from its host and port."""
        return f"http://{self.host}:{self.port}"


class Config(BaseModel):
    """Settings for the four apps."""

    model_config = ConfigDict(extra="forbid")

    ai: ServiceConfig
    backend: ServiceConfig
    database: ServiceConfig
    ui: ServiceConfig


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Read ``config.yaml`` and return the four service sections."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"config file not found: {path}") from exc
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a mapping of services")
    return Config.model_validate(raw)


config = load_config()
