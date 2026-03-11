"""
api/services/offers.py
───────────────────────
Бизнес-логика для офферов (предложений от автосервисов).

Принцип: сервис не знает о HTTP/Request/Response.
Получает данные — возвращает результат или бросает AppError.

select_offer реализует атомарный выбор оффера с пессимистической
блокировкой (FOR UPDATE) для защиты от race condition.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.exceptions import (
    AlreadySelectedError,
    ConflictError,
    ForbiddenError,
    InvalidStatusError,
    NotFoundError,
)
from api.schemas.offer import OfferCreate
from common.models.car_request import CarRequest
from common.models.enums import OfferStatusEnum, RequestStatusEnum
from common.models.offer import Offer
from common.models.service_profile import ServiceProfile

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OfferSelectResult:
    """Результат выбора оффера: оффер + данные сервиса."""
    offer: Offer
    service_profile: ServiceProfile


async def create_offer(
    db: AsyncSession,
    *,
    user_id: UUID,
    data: OfferCreate,
) -> Offer:
    """
    Создать оффер от автосервиса на заявку.

    service_id берётся из service_profile текущего пользователя.
    Проверяет, что заявка существует и не в terminal-статусе.

    Args:
        db:      AsyncSession
        user_id: UUID пользователя с role=SERVICE
        data:    Валидированные данные OfferCreate

    Returns:
        Созданный Offer

    Raises:
        NotFoundError:     если service_profile или car_request не найдены (404)
        InvalidStatusError: если заявка в terminal-статусе (422)
        ConflictError:     если сервис уже подал оффер на эту заявку (409)
    """
    # Загружаем service_profile по user_id
    sp_result = await db.execute(
        select(ServiceProfile).where(ServiceProfile.user_id == user_id)
    )
    service_profile = sp_result.scalar_one_or_none()
    if service_profile is None:
        raise NotFoundError(
            "Service profile not found. Please create your profile first."
        )

    # Загружаем заявку
    req_result = await db.execute(
        select(CarRequest).where(CarRequest.id == data.request_id)
    )
    car_request = req_result.scalar_one_or_none()
    if car_request is None:
        raise NotFoundError(f"Request {data.request_id} not found")

    # Проверяем, что заявка активна (не terminal)
    if car_request.status in RequestStatusEnum.terminal_states():
        raise InvalidStatusError(
            f"Cannot submit offer: request is in terminal status "
            f"'{car_request.status.value}'"
        )

    offer = Offer(
        request_id=data.request_id,
        service_id=service_profile.id,
        price=data.price,
        comment=data.comment,
        proposed_date=data.proposed_date,
        proposed_time=data.proposed_time,
        status=OfferStatusEnum.SENT,
    )
    db.add(offer)

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ConflictError(
            "You have already submitted an offer for this request"
        )

    logger.info(
        "offers: created id=%s request_id=%s service_id=%s price=%s",
        offer.id, data.request_id, service_profile.id, data.price,
    )
    return offer


async def get_offers_by_request(
    db: AsyncSession,
    *,
    request_id: UUID,
    user_id: UUID,
) -> list[Offer]:
    """
    Получить список офферов по заявке (для владельца заявки).

    Загружает связанный ServiceProfile через selectinload для получения
    service_name в ответе.

    Args:
        db:         AsyncSession
        request_id: UUID заявки
        user_id:    UUID текущего пользователя (должен быть владельцем)

    Returns:
        Список Offer, отсортированный по created_at ASC

    Raises:
        NotFoundError:  если заявка не найдена (404)
        ForbiddenError: если заявка не принадлежит пользователю (403)
    """
    req_result = await db.execute(
        select(CarRequest).where(CarRequest.id == request_id)
    )
    car_request = req_result.scalar_one_or_none()
    if car_request is None:
        raise NotFoundError(f"Request {request_id} not found")

    if car_request.user_id != user_id:
        raise ForbiddenError("You are not allowed to view offers for this request")

    offers_result = await db.execute(
        select(Offer)
        .where(Offer.request_id == request_id)
        .options(selectinload(Offer.service))
        .order_by(Offer.created_at.asc())
    )
    return list(offers_result.scalars().all())


async def select_offer(
    db: AsyncSession,
    *,
    offer_id: UUID,
    user_id: UUID,
) -> OfferSelectResult:
    """
    Выбрать оффер: атомарная транзакция с пессимистической блокировкой.

    Псевдокод (как в бэклоге):
        1. SELECT offer JOIN service FOR UPDATE  (блокируем строку)
        2. Если offer.status != sent → AlreadySelectedError (409)
        3. Проверяем, что request принадлежит user_id → ForbiddenError (403)
        4. UPDATE offers SET status=selected WHERE id=offer_id
        5. UPDATE offers SET status=rejected WHERE request_id=X AND id!=offer_id
        6. UPDATE car_requests SET status=selected WHERE id=request_id
        7. commit (делается get_db dependency)

    Args:
        db:       AsyncSession
        offer_id: UUID выбираемого оффера
        user_id:  UUID пользователя (должен владеть заявкой)

    Returns:
        OfferSelectResult(offer, service_profile)

    Raises:
        NotFoundError:      если оффер не найден (404)
        ForbiddenError:     если заявка не принадлежит пользователю (403)
        AlreadySelectedError: если оффер уже не в статусе sent (409)
    """
    # Шаг 1: загружаем оффер + service с блокировкой FOR UPDATE
    # with_for_update() — пессимистическая блокировка, предотвращает
    # параллельный выбор того же оффера двумя запросами.
    # SQLite не поддерживает FOR UPDATE, но тесты проходят корректно —
    # атомарность в SQLite обеспечивается на уровне транзакции.
    offer_result = await db.execute(
        select(Offer)
        .where(Offer.id == offer_id)
        .options(selectinload(Offer.service))
        .with_for_update()
    )
    offer = offer_result.scalar_one_or_none()
    if offer is None:
        raise NotFoundError(f"Offer {offer_id} not found")

    # Шаг 2: проверяем статус оффера
    if offer.status != OfferStatusEnum.SENT:
        raise AlreadySelectedError(
            f"Offer is already in status '{offer.status.value}', cannot select"
        )

    # Шаг 3: проверяем что заявка принадлежит пользователю и блокируем её
    # with_for_update() на CarRequest предотвращает двойной SELECTED при параллельных
    # запросах к разным офферам одной заявки (race condition)
    req_result = await db.execute(
        select(CarRequest).where(CarRequest.id == offer.request_id).with_for_update()
    )
    car_request = req_result.scalar_one_or_none()
    if car_request is None:
        raise NotFoundError(f"Request {offer.request_id} not found")

    if car_request.user_id != user_id:
        raise ForbiddenError("You are not allowed to select offers for this request")

    # Шаг 4: помечаем выбранный оффер
    await db.execute(
        update(Offer)
        .where(Offer.id == offer_id)
        .values(status=OfferStatusEnum.SELECTED)
    )

    # Шаг 5: отклоняем остальные офферы по этой заявке
    await db.execute(
        update(Offer)
        .where(Offer.request_id == offer.request_id, Offer.id != offer_id)
        .values(status=OfferStatusEnum.REJECTED)
    )

    # Шаг 6: обновляем статус заявки
    await db.execute(
        update(CarRequest)
        .where(CarRequest.id == offer.request_id)
        .values(status=RequestStatusEnum.SELECTED)
    )

    await db.flush()

    # Обновляем in-memory объект для ответа
    offer.status = OfferStatusEnum.SELECTED

    logger.info(
        "offers: selected id=%s request_id=%s by user_id=%s",
        offer_id, offer.request_id, user_id,
    )
    return OfferSelectResult(offer=offer, service_profile=offer.service)
