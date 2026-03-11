"""
models/offer.py
───────────────
Коммерческое предложение от автосервиса в ответ на заявку.

DDL эквивалент:

    CREATE TABLE offers (
        id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        request_id    UUID NOT NULL REFERENCES car_requests(id) ON DELETE CASCADE,
        service_id    UUID NOT NULL REFERENCES service_profiles(id) ON DELETE RESTRICT,
        price         NUMERIC(12,2) NOT NULL CHECK (price > 0),
        comment       TEXT,
        proposed_date DATE,
        proposed_time TIME,
        status        offer_status_enum NOT NULL DEFAULT 'sent',
        created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE (request_id, service_id)
    );
    CREATE INDEX idx_offers_request_id ON offers(request_id);
    CREATE INDEX idx_offers_service_id ON offers(service_id);
    CREATE INDEX idx_offers_status     ON offers(status);
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import OfferStatusEnum

if TYPE_CHECKING:
    from .car_request import CarRequest
    from .service_profile import ServiceProfile


class Offer(Base):
    """
    Предложение автосервиса по конкретной заявке.

    Ограничения:
      - Один сервис подаёт не более одного оффера на одну заявку
        (UNIQUE constraint request_id + service_id).
      - Цена > 0, хранится как NUMERIC(12,2) для точности.

    Жизненный цикл:
        sent → selected   (пользователь выбрал)
        sent → rejected   (пользователь выбрал другой оффер)
        selected, rejected — terminal, не изменяются

    При выборе оффера (PATCH /offers/{id}/select):
        1. Этот offer.status → SELECTED
        2. Все остальные офферы по request_id → REJECTED  (массовый UPDATE)
        3. car_request.status → SELECTED

    Связи:
        Offer (N) → (1) CarRequest
        Offer (N) → (1) ServiceProfile
    """

    __tablename__ = "offers"

    __table_args__ = (
        # Один сервис — один оффер на заявку
        sa.UniqueConstraint(
            "request_id",
            "service_id",
            name="uq_offers_request_service",
        ),
        # CHECK: цена должна быть положительной
        sa.CheckConstraint(
            "price > 0",
            name="ck_offers_price_positive",
        ),
        # Индекс для GET /offers/by-request/{request_id}
        sa.Index("idx_offers_request_id", "request_id"),
        # Индекс для истории откликов сервиса
        sa.Index("idx_offers_service_id", "service_id"),
        # Индекс для фильтрации по статусу
        sa.Index("idx_offers_status", "status"),
        # Partial index — только активные (ещё не resolved) офферы
        sa.Index(
            "idx_offers_pending",
            "request_id",
            postgresql_where=sa.text("status = 'sent'"),
        ),
        {"comment": "Коммерческие предложения от автосервисов"},
    )

    # ── Поля ────────────────────────────────────────────────────────────────

    request_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("car_requests.id", ondelete="CASCADE"),
        nullable=False,
        comment="FK → car_requests.id. CASCADE: при удалении заявки удаляются офферы.",
    )

    service_id: Mapped[UUID] = mapped_column(
        sa.ForeignKey("service_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        comment="FK → service_profiles.id. RESTRICT: нельзя удалить сервис с офферами.",
    )

    price: Mapped[Decimal] = mapped_column(
        sa.Numeric(12, 2),
        nullable=False,
        comment="Стоимость работ в рублях. Decimal для точных финансовых расчётов.",
    )

    comment: Mapped[str | None] = mapped_column(
        sa.Text,
        nullable=True,
        comment="Комментарий сервиса: что входит в цену, условия, материалы",
    )

    proposed_date: Mapped[datetime.date | None] = mapped_column(
        sa.Date,
        nullable=True,
        comment=(
            "Предлагаемая сервисом дата (если отличается от preferred_date заявки). "
            "NULL = подходит дата из заявки."
        ),
    )

    proposed_time: Mapped[datetime.time | None] = mapped_column(
        sa.Time,
        nullable=True,
        comment="Предлагаемое время. NULL = подходит время из заявки.",
    )

    status: Mapped[OfferStatusEnum] = mapped_column(
        sa.Enum(OfferStatusEnum, name="offer_status_enum", create_type=True),
        nullable=False,
        server_default=OfferStatusEnum.SENT.value,
        comment="Текущий статус предложения",
    )

    # ── Связи ────────────────────────────────────────────────────────────────

    request: Mapped[CarRequest] = relationship(
        "CarRequest",
        back_populates="offers",
        lazy="select",
    )

    service: Mapped[ServiceProfile] = relationship(
        "ServiceProfile",
        back_populates="offers",
        lazy="select",
    )

    # ── Свойства ─────────────────────────────────────────────────────────────

    @property
    def is_pending(self) -> bool:
        """Оффер ещё ожидает решения пользователя."""
        return self.status == OfferStatusEnum.SENT

    @property
    def effective_date(self) -> datetime.date | None:
        """Дата визита: proposed_date если указана, иначе preferred_date из заявки."""
        if self.proposed_date is not None:
            return self.proposed_date
        # Обращаемся к связанной заявке, если она загружена
        try:
            return self.request.preferred_date  # type: ignore[union-attr]
        except Exception:
            return None

    @property
    def price_display(self) -> str:
        """Форматированная цена для отображения в боте."""
        return f"{self.price:,.0f} ₽".replace(",", " ")

    def __repr__(self) -> str:
        return (
            f"<Offer id={self.id} "
            f"price={self.price} "
            f"status={self.status.value}>"
        )
