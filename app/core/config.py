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

    META_PIXEL_ID: str = ""
    META_ACCESS_TOKEN: str = ""

    TIKTOK_PIXEL_CODE: str = ""
    TIKTOK_ACCESS_TOKEN: str = ""

    SNAP_PIXEL_ID: str = ""
    SNAP_ACCESS_TOKEN: str = ""

    HASH_SALT: str = ""

    MAXMIND_ACCOUNT_ID: str = ""
    MAXMIND_LICENSE_KEY: str = ""
    ENABLE_IP_FRAUD_CHECK: bool = False
    MAXMIND_RISK_SCORE_THRESHOLD: float = 25.0
    MAXMIND_ALLOWED_COUNTRY: str = "SA"
    WHITELISTED_PHONES: str = ""

    ADMIN_USERNAME: str = ""
    ADMIN_PASSWORD: str = ""
    ADMIN_SESSION_SECRET: str = ""

    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    TABBY_SECRET_KEY: str = ""
    TABBY_MERCHANT_CODE: str = ""

    TAMARA_API_TOKEN: str = ""
    TAMARA_NOTIFICATION_TOKEN: str = ""
    TAMARA_API_URL: str = "https://api-sandbox.tamara.co"

    COD_FEE_SAR: int = 30
    SITE_URL: str = "https://sukoonhealth.shop"
    API_PUBLIC_URL: str = "https://api.sukoonhealth.shop"

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

    @property
    def whitelisted_phones(self) -> set[str]:
        return {phone.strip() for phone in self.WHITELISTED_PHONES.split(",") if phone.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
