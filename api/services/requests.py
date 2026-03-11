"""
api/services/requests.py
─────────────────────────
Бизнес-логика для заявок на ремонт (Car Requests).

Принцип: сервис не знает о HTTP/Request/Response.
Получает данные — возвращает результат или бросает AppError.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.exceptions import ForbiddenError, InvalidStatusError, NotFoundError
from api.services.common import RequestWithOffersCount
from api.schemas.request import CarRequestCreate
from common.config import settings
from common.models.car_request import CarRequest
from common.models.enums import RequestStatusEnum
from common.models.offer import Offer

logger = logging.getLogger(__name__)

# Максимальное число заявок в /requests/available без фильтра
AVAILABLE_REQUESTS_LIMIT = 50




async def create_request(
    db: AsyncSession,
    *,
    user_id: UUID,
    data: CarRequestCreate,
) -> CarRequest:
    """
    Создать заявку на ремонт.

    Validates:
        - area входит в settings.allowed_areas

    Args:
        db:      AsyncSession
        user_id: UUID владельца (берётся из current_user, не из тела запроса)
        data:    Валидированные данные из CarRequestCreate

    Returns:
        Созданный объект CarRequest

    Raises:
        InvalidStatusError: если area не входит в allowed_areas (422)
    """
    if data.area not in settings.allowed_areas:
        raise InvalidStatusError(
            f"Area '{data.area}' is not allowed. "
            f"Allowed areas: {', '.join(settings.allowed_areas)}"
        )

    request = CarRequest(
        user_id=user_id,
        car_brand=data.car_brand,
        car_model=data.car_model,
        car_year=data.car_year,
        description=data.description,
        preferred_date=data.preferred_date,
        preferred_time=data.preferred_time,
        area=data.area,
        status=RequestStatusEnum.CREATED,
    )
    db.add(request)
    await db.flush()
    logger.info(
        "requests: created id=%s user_id=%s area=%s",
        request.id, user_id, data.area,
    )
    return request


async def get_my_requests(
    db: AsyncSession,
    *,
    user_id: UUID,
) -> list[RequestWithOffersCount]:
    """
    Список заявок текущего пользователя с количеством офферов.

    Returns список RequestWithOffersCount, сортировка по created_at DESC.
    """
    # Подзапрос: количество офферов для каждой заявки
    offers_subq = (
        select(
            Offer.request_id,
            func.count(Offer.id).label("offers_count"),
        )
        .group_by(Offer.request_id)
        .subquery()
    )

    stmt = (
        select(CarRequest, func.coalesce(offers_subq.c.offers_count, 0).label("offers_count"))
        .outerjoin(offers_subq, CarRequest.id == offers_subq.c.request_id)
        .where(CarRequest.user_id == user_id)
        .order_by(CarRequest.created_at.desc())
    )

    rows = (await db.execute(stmt)).all()
    return [
        RequestWithOffersCount(request=row.CarRequest, offers_count=row.offers_count)
        for row in rows
    ]


async def get_available_requests(
    db: AsyncSession,
    *,
    area: str | None = None,
    status: RequestStatusEnum | None = None,
) -> list[CarRequest]:
    """
    Список доступных заявок для автосервисов.

    Фильтрует terminal-статусы (done, cancelled).
    Если area передан — фильтрует по area.
    Если status передан — фильтрует по статусу.
    Лимит: AVAILABLE_REQUESTS_LIMIT (50).

    Args:
        db:     AsyncSession
        area:   Фильтр по району (опциональный)
        status: Фильтр по статусу (опциональный)

    Raises:
        InvalidStatusError: если area не входит в allowed_areas (422)
    """
    if area is not None and area not in settings.allowed_areas:
        raise InvalidStatusError(
            f"Area '{area}' is not allowed. "
            f"Allowed areas: {', '.join(settings.allowed_areas)}"
        )

    terminal = RequestStatusEnum.terminal_states()

    stmt = (
        select(CarRequest)
        .where(CarRequest.status.not_in(terminal))
        .order_by(CarRequest.created_at.desc())
        .limit(AVAILABLE_REQUESTS_LIMIT)
    )

    if area is not None:
        stmt = stmt.where(CarRequest.area == area)

    if status is not None:
        stmt = stmt.where(CarRequest.status == status)

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def cancel_request(
    db: AsyncSession,
    *,
    request_id: UUID,
    user_id: UUID,
) -> CarRequest:
    """
    Отменить заявку (PATCH /requests/{id}/cancel).

    Правила:
        - Только владелец может отменить
        - Только статус created допускает отмену

    Args:
        db:         AsyncSession
        request_id: UUID заявки
        user_id:    UUID текущего пользователя (владелец)

    Returns:
        Обновлённый CarRequest (status=cancelled)

    Raises:
        NotFoundError:     если заявка не найдена (404)
        ForbiddenError:    если заявка принадлежит другому пользователю (403)
        InvalidStatusError: если статус != created (422)
    """
    result = await db.execute(
        select(CarRequest).where(CarRequest.id == request_id)
    )
    request = result.scalar_one_or_none()

    if request is None:
        raise NotFoundError(f"Request {request_id} not found")

    if request.user_id != user_id:
        raise ForbiddenError("You are not allowed to cancel this request")

    # Разрешаем отмену из CREATED и OFFERS (оба не-терминальных статуса)
    # OFFERS → CANCELLED явно указан в диаграмме состояний enums.py
    cancellable = {RequestStatusEnum.CREATED, RequestStatusEnum.OFFERS}
    if request.status not in cancellable:
        raise InvalidStatusError(
            f"Cannot cancel request with status '{request.status.value}'. "
            "Only 'created' or 'offers' requests can be cancelled."
        )

    request.status = RequestStatusEnum.CANCELLED
    await db.flush()
    logger.info("requests: cancelled id=%s by user_id=%s", request_id, user_id)
    return request
