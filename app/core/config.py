from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


ROOT = Path(__file__).resolve().parents[2]


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
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
    audio: dict[str, Any] = Field(default_factory=dict)
    websdr: dict[str, Any] = Field(default_factory=dict)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config must be a mapping: {path}")
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


_config: AppConfig | None = None


def get_config(*, refresh: bool = False) -> AppConfig:
    global _config
    if _config is not None and not refresh:
        return _config
    example = ROOT / "config" / "config.example.yaml"
    local = ROOT / "config" / "config.yaml"
    merged = _deep_merge(_load_yaml(example), _load_yaml(local))
    _config = AppConfig.model_validate(merged)
    return _config


def db_path() -> Path:
    cfg = get_config()
    path = Path(cfg.database.path)
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
