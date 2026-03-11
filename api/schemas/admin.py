"""
api/schemas/admin.py
─────────────────────
Схемы для /admin эндпоинтов.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from api.schemas.base import TimestampedMixin, _Base
from common.models.enums import RequestStatusEnum, RoleEnum


# ── Requests ──────────────────────────────────────────────────────────────────

class AdminRequestItem(TimestampedMixin):
    """
    Response item: GET /admin/requests
    Полная информация о заявке для административного просмотра.
    """
    user_id: UUID
    car_brand: str
    car_model: str
    car_year: int
    description: str
    area: str
    status: RequestStatusEnum
    offers_count: int = Field(default=0, description="Количество поступивших предложений")


class AdminRequestsListResponse(_Base):
    """Response 200: GET /admin/requests"""
    items: list[AdminRequestItem]
    total: int


# ── Users ─────────────────────────────────────────────────────────────────────

class AdminUserItem(TimestampedMixin):
    """
    Response item: GET /admin/users
    Информация о пользователе для административного просмотра.
    """
    telegram_id: int
    role: RoleEnum
    is_blocked: bool


class AdminUsersListResponse(_Base):
    """Response 200: GET /admin/users"""
    items: list[AdminUserItem]
    total: int
    page: int
    page_size: int


class AdminBlockUserResponse(_Base):
    """Response 200: PATCH /admin/users/{id}/block"""
    id: UUID
    telegram_id: int
    is_blocked: bool


# ── Stats ─────────────────────────────────────────────────────────────────────

class AdminStatsResponse(_Base):
    """
    Response 200: GET /admin/stats
    Агрегированные метрики платформы.
    """
    total_requests: int = Field(description="Всего заявок в системе")
    total_users: int = Field(description="Всего пользователей")
    total_services: int = Field(description="Всего сервисов")
    conversion_rate: float = Field(
        description="Конверсия: доля заявок, получивших хотя бы один оффер (0.0–1.0)"
    )
    avg_offers_per_request: float = Field(
        description="Среднее количество офферов на заявку (только по заявкам с офферами)"
    )
    requests_by_status: dict[str, int] = Field(
        description="Количество заявок по каждому статусу"
    )
