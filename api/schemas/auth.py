"""
api/schemas/auth.py
────────────────────
Схемы для POST /auth/telegram.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator

from api.schemas.base import _Base
from common.models.enums import RoleEnum


class AuthTelegramRequest(_Base):
    """
    Request body: POST /auth/telegram
    Вызывается ботом при первом /start пользователя.
    """
    telegram_id: int = Field(
        gt=0,
        description="Telegram user ID (положительное целое)",
        examples=[123456789],
    )
    role: RoleEnum = Field(
        description="Роль: 'user' или 'service'. 'admin' создаётся вручную.",
        examples=["user"],
    )

    @field_validator("role")
    @classmethod
    def role_not_admin(cls, v: RoleEnum) -> RoleEnum:
        """Нельзя самостоятельно зарегистрироваться как admin."""
        if v == RoleEnum.ADMIN:
            raise ValueError("Cannot register with role 'admin'")
        return v


class AuthTelegramResponse(_Base):
    """
    Response 200: POST /auth/telegram
    Возвращается и при создании, и при повторном вызове (idempotent lookup).
    """
    user_id: UUID = Field(description="Внутренний UUID пользователя")
    role: RoleEnum
    is_new: bool = Field(description="True — пользователь создан, False — уже существовал")
    created_at: datetime
