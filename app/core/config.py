from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_ENV: str = "development"
    APP_NAME: str = "Sukoon Health API"
    FRONTEND_ORIGIN: str = "https://sukoonhealth.shop"

    DATABASE_URL: str = "postgresql+asyncpg://sukoonhealth:password@localhost:5432/sukoonhealth"

    GOOGLE_SHEETS_WEBHOOK_URL: str = ""
    GOOGLE_SHEETS_WEBHOOK_SECRET: str = ""

    META_PIXEL_ID: str = ""
    META_ACCESS_TOKEN: str = ""

    TIKTOK_PIXEL_CODE: str = ""
    TIKTOK_ACCESS_TOKEN: str = ""

    SNAP_PIXEL_ID: str = ""
    SNAP_ACCESS_TOKEN: str = ""

    HASH_SALT: str = ""

    @field_validator("APP_ENV")
    @classmethod
    def validate_env(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"APP_ENV must be one of {allowed}")
        return v

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def allowed_origins(self) -> list[str]:
        origins = [self.FRONTEND_ORIGIN]
        if not self.is_production:
            origins += [
                "http://localhost:3000",
                "http://localhost:5173",
                "http://localhost:8080",
                "http://127.0.0.1:3000",
            ]
        return origins


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
