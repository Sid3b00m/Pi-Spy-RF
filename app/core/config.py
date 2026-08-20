from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


ROOT = Path(__file__).resolve().parents[2]


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080


class AuthConfig(BaseModel):
    enabled: bool = False
    username: str = "ops"
    password: str = ""


class DatabaseConfig(BaseModel):
    path: str = "data/pi_spy.db"


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    server: ServerConfig = Field(default_factory=ServerConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    devices: dict[str, Any] = Field(default_factory=dict)
    wifi: dict[str, Any] = Field(default_factory=dict)
    bluetooth: dict[str, Any] = Field(default_factory=dict)
    mac_db: dict[str, Any] = Field(default_factory=dict)
    decode: dict[str, Any] = Field(default_factory=dict)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config must be a mapping: {path}")
    return data


@lru_cache
def get_config() -> AppConfig:
    example = ROOT / "config" / "config.example.yaml"
    local = ROOT / "config" / "config.yaml"
    merged = _load_yaml(example)
    merged.update(_load_yaml(local))
    return AppConfig.model_validate(merged)


def db_path() -> Path:
    cfg = get_config()
    path = Path(cfg.database.path)
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path