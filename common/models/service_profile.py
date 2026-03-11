"""
models/service_profile.py
──────────────────────────
Профиль автосервиса — заполняется при регистрации с role=SERVICE.

DDL эквивалент:

    CREATE TABLE service_profiles (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id     UUID NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
        name        TEXT NOT NULL,
        description TEXT,
        areas       TEXT[] NOT NULL DEFAULT '{}',
        services    TEXT[] NOT NULL DEFAULT '{}',
        phone       TEXT NOT NULL,
        is_active   BOOLEAN NOT NULL DEFAULT TRUE,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE UNIQUE INDEX idx_sp_user_id ON service_profiles(user_id);
    CREATE INDEX        idx_sp_areas   ON service_profiles USING GIN(areas);
    CREATE INDEX        idx_sp_active  ON service_profiles(is_active)
                        WHERE is_active = TRUE;
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .offer import Offer
    from .user import User


class ServiceProfile(Base):
    """
    Профиль автосервиса.

    Один User (role=SERVICE) — ровно один ServiceProfile (1:1).

    Поля areas и services хранятся как PostgreSQL TEXT[].
    При выборке доступных заявок используется GIN-индекс
    для быстрого пересечения: array_overlap(areas, request.area).

    Связи:
        ServiceProfile (N) → (1) User
        ServiceProfile (1) → (N) Offer
    """

    __tablename__ = "service_profiles"

    __table_args__ = (
        # UNIQUE — один пользователь = один профиль
        sa.Index("idx_sp_user_id", "user_id", unique=True),
        # GIN для быстрого поиска по массиву районов
        sa.Index("idx_sp_areas", "areas", postgresql_using="gin"),
        # Partial index — только активные профили (для маршрутизации заявок)
        sa.Index(
            "idx_sp_active",
            "is_active",
            postgresql_where=sa.text("is_active = TRUE"),
        ),
        {"comment": "Профили автосервисов"},
    )

    # ── Поля ────────────────────────────────────────────────────────────────

    user_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        comment="FK → users.id (1:1)",
    )

    name: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
        comment="Публичное название автосервиса",
    )

    description: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        comment="Произвольное описание (опционально)",
    )

    areas: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text),
        nullable=False,
        server_default="{}",
        comment="Массив районов обслуживания (из конфига допустимых значений)",
    )

    services: Mapped[list[str]] = mapped_column(
        ARRAY(sa.Text),
        nullable=False,
        server_default="{}",
        comment="Массив типов работ (ТО, Тормоза, Подвеска и т.д.)",
    )

    phone: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
        comment="Контактный телефон в формате +7XXXXXXXXXX",
    )

    is_active: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.true(),
        comment="Активен ли профиль (может быть деактивирован администратором)",
    )

    # ── Связи ────────────────────────────────────────────────────────────────

    user: Mapped[User] = relationship(
        "User",
        back_populates="service_profile",
        lazy="select",
    )

    offers: Mapped[list[Offer]] = relationship(
        "Offer",
        back_populates="service",
        cascade="save-update, merge",   # RESTRICT при удалении — не cascade
        lazy="select",
        doc="Все предложения от этого сервиса",
    )

    # ── Методы ───────────────────────────────────────────────────────────────

    def covers_area(self, area: str) -> bool:
        """Проверяет, работает ли сервис в указанном районе."""
        return area in self.areas

    def __repr__(self) -> str:
        return f"<ServiceProfile id={self.id} name={self.name!r} active={self.is_active}>"
