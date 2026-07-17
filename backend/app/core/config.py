from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACKEND_DIR.parent
DEVELOPMENT_SECRET_KEY = "development-only-secret-key-change-before-production"
DEFAULT_DEVELOPMENT_CORS_ORIGINS = "http://localhost:5173"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "福兰特轻量生产计划执行系统"
    app_version: str = "0.1.0"
    app_env: str = "development"
    database_url: str = "sqlite:///./data/flante_mes.db"
    secret_key: str = DEVELOPMENT_SECRET_KEY
    access_token_expire_minutes: int = 480
    initial_admin_username: str = "admin"
    initial_admin_password: str | None = None
    cors_origins: str | None = None

    @model_validator(mode="after")
    def validate_runtime_safety(self) -> "Settings":
        if len(self.secret_key) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters long")
        if self.is_production:
            if self.secret_key == DEVELOPMENT_SECRET_KEY:
                raise ValueError("SECRET_KEY must not use the development default in production")
            if not self.initial_admin_password or not self.initial_admin_password.strip():
                raise ValueError("INITIAL_ADMIN_PASSWORD is required in production")
            if not self.cors_origins or not self.cors_origin_list:
                raise ValueError("CORS_ORIGINS must be explicitly configured in production")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        origins = self.cors_origins or DEFAULT_DEVELOPMENT_CORS_ORIGINS
        return [item.strip() for item in origins.split(",") if item.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
