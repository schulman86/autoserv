"""
api/routers/admin.py
─────────────────────
Роутер для административного API.

Эндпоинты:
    GET   /requests          — все заявки с фильтрацией (role=admin)
    GET   /users             — список пользователей с пагинацией (role=admin)
    PATCH /users/{id}/block  — заблокировать пользователя (role=admin)
    GET   /stats             — метрики платформы (role=admin)

Все эндпоинты требуют role=admin (AdminOnly dependency).
Роутер тонкий: только HTTP-слой. Логика — в api/services/admin.py.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from api.dependencies.auth import AdminOnly
from api.dependencies.db import DbSession
from api.schemas.admin import (
    AdminBlockUserResponse,
    AdminRequestItem,
    AdminRequestsListResponse,
    AdminStatsResponse,
    AdminUserItem,
    AdminUsersListResponse,
)
from api.services.admin import (
    USERS_PAGE_SIZE_DEFAULT,
    USERS_PAGE_SIZE_MAX,
    block_user,
    get_admin_requests,
    get_admin_users,
    get_stats,
)
from common.models.enums import RequestStatusEnum

router = APIRouter()


@router.get(
    "/requests",
    response_model=AdminRequestsListResponse,
    summary="Все заявки с фильтрацией",
    responses={
        200: {"description": "Список всех заявок"},
        401: {"description": "Не аутентифицирован или заблокирован"},
        403: {"description": "Только для role=admin"},
    },
)
async def list_requests(
    _: AdminOnly,
    db: DbSession,
    status: RequestStatusEnum | None = Query(default=None, description="Фильтр по статусу"),
    area: str | None = Query(default=None, description="Фильтр по району"),
    page: int = Query(default=1, ge=1, description="Страница"),
    page_size: int = Query(default=50, ge=1, le=200, description="Размер страницы (1–200)"),
) -> AdminRequestsListResponse:
    rows = await get_admin_requests(db, status=status, area=area, page=page, page_size=page_size)
    items = [
        AdminRequestItem(
            id=row.request.id,
            created_at=row.request.created_at,
            user_id=row.request.user_id,
            car_brand=row.request.car_brand,
            car_model=row.request.car_model,
            car_year=row.request.car_year,
            description=row.request.description,
            area=row.request.area,
            status=row.request.status,
            offers_count=row.offers_count,
        )
        for row in rows
    ]
    return AdminRequestsListResponse(items=items, total=len(items))


@router.get(
    "/users",
    response_model=AdminUsersListResponse,
    summary="Список пользователей с пагинацией",
    responses={
        200: {"description": "Список пользователей"},
        401: {"description": "Не аутентифицирован или заблокирован"},
        403: {"description": "Только для role=admin"},
    },
)
async def list_users(
    _: AdminOnly,
    db: DbSession,
    page: int = Query(default=1, ge=1, description="Номер страницы (с 1)"),
    page_size: int = Query(
        default=USERS_PAGE_SIZE_DEFAULT,
        ge=1,
        le=USERS_PAGE_SIZE_MAX,
        description=f"Размер страницы (1–{USERS_PAGE_SIZE_MAX})",
    ),
) -> AdminUsersListResponse:
    users, total = await get_admin_users(db, page=page, page_size=page_size)
    items = [AdminUserItem.model_validate(u) for u in users]
    return AdminUsersListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/users/{user_id}/block",
    response_model=AdminBlockUserResponse,
    summary="Заблокировать или разблокировать пользователя",
    responses={
        200: {"description": "Статус блокировки обновлён"},
        401: {"description": "Не аутентифицирован или заблокирован"},
        403: {"description": "Только для role=admin / нельзя блокировать себя или другого admin"},
        404: {"description": "Пользователь не найден"},
    },
)
async def block_user_endpoint(
    user_id: UUID,
    current_admin: AdminOnly,
    db: DbSession,
    block: bool = Query(description="true = заблокировать, false = разблокировать"),
) -> AdminBlockUserResponse:
    user = await block_user(
        db,
        target_user_id=user_id,
        admin_user_id=current_admin.id,
        block=block,
    )
    return AdminBlockUserResponse(
        id=user.id,
        telegram_id=user.telegram_id,
        is_blocked=user.is_blocked,
    )


@router.get(
    "/stats",
    response_model=AdminStatsResponse,
    summary="Метрики платформы",
    responses={
        200: {"description": "Агрегированные метрики"},
        401: {"description": "Не аутентифицирован или заблокирован"},
        403: {"description": "Только для role=admin"},
    },
)
async def stats(
    _: AdminOnly,
    db: DbSession,
) -> AdminStatsResponse:
    result = await get_stats(db)
    return AdminStatsResponse(
        total_requests=result.total_requests,
        total_users=result.total_users,
        total_services=result.total_services,
        conversion_rate=result.conversion_rate,
        avg_offers_per_request=result.avg_offers_per_request,
        requests_by_status=result.requests_by_status,
    )
