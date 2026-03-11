"""
api/routers/requests.py
────────────────────────
Роутер для заявок на ремонт.

Эндпоинты:
    POST   /                  — создать заявку (user only)
    GET    /my                — список своих заявок (user only)
    GET    /available         — доступные заявки (service only)
    PATCH  /{id}/cancel       — отменить заявку (user only, только created)

Роутер тонкий: только HTTP-слой. Логика — в api/services/requests.py.
Уведомления — BackgroundTask через api/services/notifications.py.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query

from api.dependencies.auth import CurrentUser, ServiceOnly, UserOnly
from api.dependencies.db import DbSession
from api.schemas.request import (
    AvailableRequestsListResponse,
    CarRequestCreate,
    CarRequestCreateResponse,
    CarRequestDetail,
    CarRequestListResponse,
    CarRequestSummary,
)
from api.services.notifications import notify_services_new_request
from api.services.requests import (
    cancel_request,
    create_request,
    get_available_requests,
    get_my_requests,
)
from common.models.database import AsyncSessionFactory
from common.models.enums import RequestStatusEnum

router = APIRouter()


@router.post(
    "/",
    response_model=CarRequestCreateResponse,
    status_code=201,
    summary="Создать заявку на ремонт",
    responses={
        201: {"description": "Заявка создана"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Только для role=user"},
        422: {"description": "Невалидные данные / недопустимый район"},
    },
)
async def create(
    body: CarRequestCreate,
    current_user: UserOnly,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> CarRequestCreateResponse:
    request = await create_request(db, user_id=current_user.id, data=body)

    # Сохраняем примитивы ДО закрытия сессии.
    # К моменту выполнения BackgroundTask основная транзакция закоммичена
    # и ORM-объект detached — передавать его нельзя.
    _rid = request.id
    _area = request.area
    _brand = request.car_brand
    _model = request.car_model
    _year = request.car_year
    _desc = request.description
    _date = request.preferred_date
    _time = request.preferred_time

    async def _notify_services() -> None:
        async with AsyncSessionFactory() as notify_db:
            await notify_services_new_request(
                notify_db,
                request_id=_rid, area=_area,
                car_brand=_brand, car_model=_model, car_year=_year,
                description=_desc, preferred_date=_date, preferred_time=_time,
            )

    background_tasks.add_task(_notify_services)

    return CarRequestCreateResponse.model_validate(request)


@router.get(
    "/my",
    response_model=CarRequestListResponse,
    summary="Список своих заявок",
    responses={
        200: {"description": "Список заявок пользователя с количеством офферов"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Только для role=user"},
    },
)
async def my_requests(
    current_user: UserOnly,
    db: DbSession,
) -> CarRequestListResponse:
    items_with_count = await get_my_requests(db, user_id=current_user.id)
    summaries = [
        CarRequestSummary(
            id=row.request.id,
            created_at=row.request.created_at,
            car_brand=row.request.car_brand,
            car_model=row.request.car_model,
            car_year=row.request.car_year,
            area=row.request.area,
            status=row.request.status,
            offers_count=row.offers_count,
        )
        for row in items_with_count
    ]
    return CarRequestListResponse(items=summaries, total=len(summaries))


@router.get(
    "/available",
    response_model=AvailableRequestsListResponse,
    summary="Доступные заявки для автосервисов",
    responses={
        200: {"description": "Список активных заявок (не terminal), max 50"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Только для role=service"},
        422: {"description": "Недопустимый район"},
    },
)
async def available_requests(
    _: ServiceOnly,
    db: DbSession,
    area: str | None = Query(default=None, description="Фильтр по району"),
    status: RequestStatusEnum | None = Query(default=None, description="Фильтр по статусу"),
) -> AvailableRequestsListResponse:
    requests = await get_available_requests(db, area=area, status=status)
    details = [CarRequestDetail.model_validate(r) for r in requests]
    return AvailableRequestsListResponse(items=details, total=len(details))


@router.patch(
    "/{request_id}/cancel",
    response_model=CarRequestCreateResponse,
    summary="Отменить заявку",
    responses={
        200: {"description": "Заявка отменена"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Только владелец может отменить / role=user"},
        404: {"description": "Заявка не найдена"},
        422: {"description": "Нельзя отменить заявку в текущем статусе"},
    },
)
async def cancel(
    request_id: UUID,
    current_user: UserOnly,
    db: DbSession,
) -> CarRequestCreateResponse:
    request = await cancel_request(
        db, request_id=request_id, user_id=current_user.id
    )
    return CarRequestCreateResponse.model_validate(request)
