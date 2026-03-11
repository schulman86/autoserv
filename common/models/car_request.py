"""
models/car_request.py
──────────────────────
Заявка на ремонт/обслуживание от владельца автомобиля.

DDL эквивалент:

    CREATE TABLE car_requests (
        id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id        UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        car_brand      TEXT NOT NULL,
        car_model      TEXT NOT NULL,
        car_year       INT  NOT NULL CHECK (car_year BETWEEN 1990 AND 2030),
        description    TEXT NOT NULL,
        preferred_date DATE NOT NULL,
        preferred_time TIME NOT NULL,
        area           TEXT NOT NULL,
        status         request_status_enum NOT NULL DEFAULT 'created',
        created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX idx_requests_user_id     ON car_requests(user_id);
    CREATE INDEX idx_requests_area_status ON car_requests(area, status);
    CREATE INDEX idx_requests_created_at  ON car_requests(created_at DESC);
    CREATE INDEX idx_requests_status      ON car_requests(status)
                 WHERE status NOT IN ('done', 'cancelled');
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import RequestStatusEnum

if TYPE_CHECKING:
    from .offer import Offer
    from .user import User


# Год выпуска: разумный диапазон для MVP
YEAR_MIN = 1990
YEAR_MAX = 2030


class CarRequest(Base):
    """
    Заявка на ремонт/обслуживание автомобиля.

    Жизненный цикл:
        created → offers → selected → done
                         ↘ cancelled (из любого не-terminal)

    После создания заявка рассылается активным сервисам в area.
    Статус обновляется backend-ом:
        - created → offers: при первом оффере (PATCH offers)
        - offers  → selected: при выборе оффера пользователем
        - selected → done: ручная отметка (v1.1+)

    Связи:
        CarRequest (N) → (1) User
        CarRequest (1) → (N) Offer
    """

    __tablename__ = "car_requests"

    __table_args__ = (
        # Проверка года выпуска на уровне БД
        sa.CheckConstraint(
            f"car_year BETWEEN {YEAR_MIN} AND {YEAR_MAX}",
            name="ck_car_requests_year_range",
        ),
        # FK-индекс: список заявок пользователя (GET /requests/my)
        sa.Index("idx_requests_user_id", "user_id"),
        # Составной индекс — основной для GET /requests/available?area=...
        sa.Index("idx_requests_area_status", "area", "status"),
        # Индекс для сортировки по дате создания
        sa.Index(
            "idx_requests_created_at",
            sa.text("created_at DESC"),
        ),
        # Partial index — только активные заявки (не terminal)
        sa.Index(
            "idx_requests_active",
            "status",
            postgresql_where=sa.text("status NOT IN ('done', 'cancelled')"),
        ),
        {"comment": "Заявки на ремонт/обслуживание от владельцев авто"},
    )

    # ── Поля ────────────────────────────────────────────────────────────────

    user_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        comment="FK → users.id. RESTRICT: нельзя удалить пользователя с заявками.",
    )

    car_brand: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
        comment="Марка автомобиля (напр. Toyota, BMW)",
    )

    car_model: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
        comment="Модель автомобиля (напр. Camry, X5)",
    )

    car_year: Mapped[int] = mapped_column(
        sa.Integer,
        nullable=False,
        comment=f"Год выпуска. Диапазон: {YEAR_MIN}–{YEAR_MAX}",
    )

    description: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
        comment="Свободное описание проблемы от пользователя (min 10 символов)",
    )

    preferred_date: Mapped[datetime.date] = mapped_column(
        sa.Date,
        nullable=False,
        comment="Желаемая дата записи (должна быть >= сегодня)",
    )

    preferred_time: Mapped[datetime.time] = mapped_column(
        sa.Time,
        nullable=False,
        comment="Желаемое время записи",
    )

    area: Mapped[str] = mapped_column(
        sa.Text,
        nullable=False,
        comment="Район города из конфига допустимых значений",
    )

    status: Mapped[RequestStatusEnum] = mapped_column(
        sa.Enum(RequestStatusEnum, name="request_status_enum", create_type=True),
        nullable=False,
        server_default=RequestStatusEnum.CREATED.value,
        comment="Текущий статус заявки в жизненном цикле",
    )

    # ── Связи ────────────────────────────────────────────────────────────────

    user: Mapped[User] = relationship(
        "User",
        back_populates="car_requests",
        lazy="select",
    )

    offers: Mapped[list[Offer]] = relationship(
        "Offer",
        back_populates="request",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="Offer.created_at",
        doc="Все предложения по этой заявке",
    )

    # ── Свойства ─────────────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        """Заявка принимает офферы и доступна для действий."""
        return self.status not in RequestStatusEnum.terminal_states()

    @property
    def car_display(self) -> str:
        """Форматированное название автомобиля."""
        return f"{self.car_brand} {self.car_model} ({self.car_year})"

    @property
    def selected_offer(self) -> Offer | None:
        """Выбранный оффер или None."""
        from .enums import OfferStatusEnum
        return next(
            (o for o in self.offers if o.status == OfferStatusEnum.SELECTED),
            None,
        )

    def __repr__(self) -> str:
        return (
            f"<CarRequest id={self.id} "
            f"car={self.car_display!r} "
            f"area={self.area!r} "
            f"status={self.status.value}>"
        )
