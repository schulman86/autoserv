"""
api/schemas/service_profile.py
────────────────────────────────
Схемы для /service-profile эндпоинтов.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, field_validator

from api.schemas.base import TimestampedMixin, _Base


class ServiceProfileUpsert(_Base):
    """
    Request body: POST /service-profile
    Idempotent: создаёт или обновляет профиль.
    """
    name: str = Field(min_length=1, max_length=200, examples=["АвтоМастер"])
    description: str | None = Field(
        default=None,
        max_length=2000,
        examples=["Опытные мастера с 2010 года"],
    )
    areas: list[str] = Field(
        min_length=1,
        description="Районы обслуживания (минимум один)",
        examples=[["Центр", "Юг"]],
    )
    services: list[str] = Field(
        min_length=1,
        description="Типы работ (минимум один)",
        examples=[["ТО", "Тормоза", "Подвеска"]],
    )
    phone: str = Field(
        pattern=r"^\+7\d{10}$",
        examples=["+79990001122"],
        description="Телефон в формате +7XXXXXXXXXX",
    )

    @field_validator("areas", "services")
    @classmethod
    def no_empty_strings(cls, v: list[str]) -> list[str]:
        cleaned = [item.strip() for item in v if item.strip()]
        if not cleaned:
            raise ValueError("List must contain at least one non-empty item")
        return cleaned


class ServiceProfileResponse(TimestampedMixin):
    """
    Response: POST /service-profile, GET /service-profile/me
    """
    user_id: UUID
    name: str
    description: str | None
    areas: list[str]
    services: list[str]
    phone: str
    is_active: bool
