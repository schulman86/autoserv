"""
common/config/settings.py
─────────────────────────
Централизованная конфигурация приложения.

Источники (в порядке приоритета):
  1. Переменные окружения
  2. Файл .env в корне репозитория
  3. Значения по умолчанию

Использование:
    from common.config import settings
    print(settings.database_url)
"""

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/autoservice",
        description="Async PostgreSQL DSN (asyncpg driver)",
    )

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )

    # ── Telegram ──────────────────────────────────────────────────────────────
    bot_token: str = Field(
        description="Telegram Bot API token from @BotFather",
    )

    # ── API ───────────────────────────────────────────────────────────────────
    api_base_url: str = Field(
        default="http://localhost:8000",
        description="Internal API base URL (used by bot)",
    )
    api_internal_secret: str = Field(
        default="change-me-in-production",
        description="Shared secret for bot→api internal requests",
    )

    # ── Business config ───────────────────────────────────────────────────────
    allowed_areas: Annotated[list[str], Field(default_factory=list)] = Field(
        default=["Центр", "Север", "Юг", "Восток", "Запад"],
        description="Allowed city areas (comma-separated in env)",
    )

    # ── Admin ─────────────────────────────────────────────────────────────────
    admin_telegram_ids: Annotated[list[int], Field(default_factory=list)] = Field(
        default=[],
        description="Telegram IDs with admin access (comma-separated in env)",
    )

    # ── App ───────────────────────────────────────────────────────────────────
    app_env: str = Field(
        default="development",
        pattern="^(development|production|test)$",
    )

    @field_validator("allowed_areas", mode="before")
    @classmethod
    def parse_areas(cls, v: object) -> list[str]:
        """Accept comma-separated string or list."""
        if isinstance(v, str):
            return [a.strip() for a in v.split(",") if a.strip()]
        return list(v)  # type: ignore[arg-type]

    @field_validator("admin_telegram_ids", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: object) -> list[int]:
        """Accept comma-separated string or list."""
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return list(v)  # type: ignore[arg-type]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Синглтон настроек. Кешируется после первого вызова.
    В тестах переопределять через:
        app.dependency_overrides[get_settings] = lambda: Settings(...)
    """
    return Settings()


# Удобный алиас для импорта
settings: Settings = get_settings()
