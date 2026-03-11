"""
models/user.py
──────────────
Таблица users — единая для всех ролей (владелец авто / сервис / admin).

DDL эквивалент:

    CREATE TABLE users (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        telegram_id BIGINT NOT NULL UNIQUE,
        role        role_enum NOT NULL,
        is_blocked  BOOLEAN NOT NULL DEFAULT FALSE,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE UNIQUE INDEX idx_users_telegram_id ON users(telegram_id);
    CREATE INDEX        idx_users_role        ON users(role);
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import RoleEnum

if TYPE_CHECKING:
    # Циклические импорты только для аннотаций
    from .car_request import CarRequest
    from .service_profile import ServiceProfile


class User(Base):
    """
    Пользователь системы.

    Один пользователь — одна роль.
    Роль задаётся при первом /start и не меняется на MVP.

    Связи:
        User (1) → (N) CarRequest      — для role=USER
        User (1) → (1) ServiceProfile  — для role=SERVICE
    """

    __tablename__ = "users"

    __table_args__ = (
        # Уникальный индекс по telegram_id — основной путь поиска при авторизации
        sa.Index("idx_users_telegram_id", "telegram_id", unique=True),
        # Индекс по role — для admin-панели и фильтрации
        sa.Index("idx_users_role", "role"),
        {
            "comment": "Пользователи системы (все роли)",
        },
    )

    # ── Поля ────────────────────────────────────────────────────────────────

    telegram_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        unique=True,
        comment="Уникальный Telegram user ID. Источник истины для авторизации.",
    )

    role: Mapped[RoleEnum] = mapped_column(
        sa.Enum(RoleEnum, name="role_enum", create_type=True),
        nullable=False,
        comment="Роль пользователя в системе: user / service / admin",
    )

    is_blocked: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.false(),
        default=False,
        comment="Заблокирован ли пользователь администратором",
    )

    # ── Связи (lazy="select" — стандарт для async, используем selectinload) ─

    car_requests: Mapped[list[CarRequest]] = relationship(
        "CarRequest",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
        doc="Заявки пользователя (только для role=USER)",
    )

    service_profile: Mapped[ServiceProfile | None] = relationship(
        "ServiceProfile",
        back_populates="user",
        uselist=False,              # One-to-one
        cascade="all, delete-orphan",
        lazy="select",
        doc="Профиль автосервиса (только для role=SERVICE)",
    )

    # ── Свойства ─────────────────────────────────────────────────────────────

    @property
    def is_service(self) -> bool:
        return self.role == RoleEnum.SERVICE

    @property
    def is_admin(self) -> bool:
        return self.role == RoleEnum.ADMIN

    def __repr__(self) -> str:
        return f"<User id={self.id} tg={self.telegram_id} role={self.role.value}>"
