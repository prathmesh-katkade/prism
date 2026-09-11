from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_prefix="PRISM_")

    api_title: str = "PRISM Platform API"
    api_version: str = "0.1.0"
    allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    )
    request_timeout_seconds: float = Field(default=15.0, gt=0, le=120)


@lru_cache
def get_settings() -> Settings:
    return Settings()
