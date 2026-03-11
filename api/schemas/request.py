"""
api/schemas/request.py
───────────────────────
Схемы для /requests эндпоинтов.
"""

from __future__ import annotations

import datetime
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from api.schemas.base import TimestampedMixin, _Base
from common.models.car_request import YEAR_MAX, YEAR_MIN  # единственный источник истины
from common.models.enums import RequestStatusEnum



class CarRequestCreate(_Base):
    """Request body: POST /requests"""
    car_brand: str = Field(min_length=1, max_length=100, examples=["Toyota"])
    car_model: str = Field(min_length=1, max_length=100, examples=["Camry"])
    car_year: int = Field(ge=YEAR_MIN, le=YEAR_MAX, examples=[2018])
    description: str = Field(
        min_length=10,
        max_length=2000,
        examples=["Замена тормозных колодок, скрип при торможении"],
    )
    preferred_date: datetime.date = Field(examples=["2026-03-01"])
    preferred_time: datetime.time = Field(examples=["12:00:00"])
    area: str = Field(min_length=1, examples=["Центр"])

    @field_validator("preferred_date")
    @classmethod
    def date_not_in_past(cls, v: datetime.date) -> datetime.date:
        if v < datetime.date.today():
            raise ValueError("preferred_date cannot be in the past")
        return v


class CarRequestCreateResponse(_Base):
    """Response 201: POST /requests"""
    id: UUID
    status: RequestStatusEnum
    created_at: datetime.datetime


class CarRequestSummary(TimestampedMixin):
    """
    Response item: GET /requests/my
    Краткая информация для списка заявок пользователя.
    """
    car_brand: str
    car_model: str
    car_year: int
    area: str
    status: RequestStatusEnum
    offers_count: int = Field(default=0, description="Количество полученных предложений")

    @property
    def car_display(self) -> str:
        return f"{self.car_brand} {self.car_model} ({self.car_year})"


class CarRequestDetail(TimestampedMixin):
    """
    Response item: GET /requests/available
    Полная информация для страницы детализации заявки.
    """
    car_brand: str
    car_model: str
    car_year: int
    description: str
    preferred_date: datetime.date
    preferred_time: datetime.time
    area: str
    status: RequestStatusEnum


class CarRequestListResponse(_Base):
    """Response 200: GET /requests/my"""
    items: list[CarRequestSummary]
    total: int


class AvailableRequestsListResponse(_Base):
    """Response 200: GET /requests/available"""
    items: list[CarRequestDetail]
    total: int
