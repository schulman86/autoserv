"""
api/schemas/offer.py
─────────────────────
Схемы для /offers эндпоинтов.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from api.schemas.base import TimestampedMixin, _Base
from common.models.enums import OfferStatusEnum


class OfferCreate(_Base):
    """Request body: POST /offers"""
    request_id: UUID = Field(description="UUID заявки, на которую отвечает сервис")
    price: Decimal = Field(
        gt=0,
        max_digits=12,
        decimal_places=2,
        examples=[4500.00],
        description="Стоимость работ в рублях",
    )
    comment: str | None = Field(
        default=None,
        max_length=1000,
        examples=["Оригинальные колодки, 1 час работы"],
    )
    proposed_date: datetime.date | None = Field(
        default=None,
        description="Альтернативная дата (None = подходит дата из заявки)",
    )
    proposed_time: datetime.time | None = Field(
        default=None,
        description="Альтернативное время (None = подходит время из заявки)",
    )


class OfferCreateResponse(_Base):
    """Response 201: POST /offers"""
    id: UUID
    status: OfferStatusEnum


class OfferDetail(TimestampedMixin):
    """
    Response item: GET /offers/by-request/{request_id}
    Включает публичные данные сервиса для выбора.
    """
    service_name: str = Field(description="Название автосервиса")
    price: Decimal
    comment: str | None
    proposed_date: datetime.date | None
    proposed_time: datetime.time | None
    status: OfferStatusEnum


class OfferSelectRequest(_Base):
    """Request body: PATCH /offers/{offer_id}/select"""
    confirm: bool = Field(
        description="Должно быть true — явное подтверждение выбора",
    )


class OfferSelectResponse(_Base):
    """
    Response 200: PATCH /offers/{offer_id}/select
    Возвращает контакты выбранного сервиса.
    """
    offer_id: UUID
    status: OfferStatusEnum
    service_name: str
    service_phone: str = Field(description="Контактный телефон сервиса")


class OfferListResponse(_Base):
    """Response 200: GET /offers/by-request/{request_id}"""
    items: list[OfferDetail]
    total: int
