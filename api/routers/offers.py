"""
api/routers/offers.py
──────────────────────
Роутер для офферов (предложений автосервисов).

Эндпоинты:
    POST  /                           — создать оффер (service only)
    GET   /by-request/{request_id}    — список офферов по заявке (user only)
    PATCH /{offer_id}/select          — выбрать оффер (user only)

Роутер тонкий: только HTTP-слой. Логика — в api/services/offers.py.
Уведомления — BackgroundTask через api/services/notifications.py.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks

from api.dependencies.auth import CurrentUser, ServiceOnly, UserOnly
from api.dependencies.db import DbSession
from api.schemas.offer import (
    OfferCreate,
    OfferCreateResponse,
    OfferDetail,
    OfferListResponse,
    OfferSelectRequest,
    OfferSelectResponse,
)
from api.services.notifications import notify_service_offer_selected, notify_user_new_offer
from api.services.offers import create_offer, get_offers_by_request, select_offer
from common.models.database import AsyncSessionFactory

router = APIRouter()


@router.post(
    "/",
    response_model=OfferCreateResponse,
    status_code=201,
    summary="Создать предложение (оффер) по заявке",
    responses={
        201: {"description": "Оффер создан"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Только для role=service"},
        404: {"description": "Заявка или профиль сервиса не найдены"},
        409: {"description": "Уже подан оффер на эту заявку"},
        422: {"description": "Заявка в terminal-статусе"},
    },
)
async def create(
    body: OfferCreate,
    current_user: ServiceOnly,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> OfferCreateResponse:
    offer = await create_offer(db, user_id=current_user.id, data=body)

    # Передаём UUID — к моменту BackgroundTask сессия уже закрыта
    _offer_id = offer.id

    async def _notify_user() -> None:
        async with AsyncSessionFactory() as notify_db:
            await notify_user_new_offer(notify_db, offer_id=_offer_id)

    background_tasks.add_task(_notify_user)

    return OfferCreateResponse(id=offer.id, status=offer.status)


@router.get(
    "/by-request/{request_id}",
    response_model=OfferListResponse,
    summary="Список офферов по заявке",
    responses={
        200: {"description": "Список предложений с деталями сервисов"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Только владелец заявки / role=user"},
        404: {"description": "Заявка не найдена"},
    },
)
async def list_by_request(
    request_id: UUID,
    current_user: UserOnly,
    db: DbSession,
) -> OfferListResponse:
    offers = await get_offers_by_request(
        db, request_id=request_id, user_id=current_user.id
    )
    details = [
        OfferDetail(
            id=o.id,
            created_at=o.created_at,
            service_name=o.service.name,
            price=o.price,
            comment=o.comment,
            proposed_date=o.proposed_date,
            proposed_time=o.proposed_time,
            status=o.status,
        )
        for o in offers
    ]
    return OfferListResponse(items=details, total=len(details))


@router.patch(
    "/{offer_id}/select",
    response_model=OfferSelectResponse,
    summary="Выбрать оффер",
    responses={
        200: {"description": "Оффер выбран, возвращаются контакты сервиса"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Только владелец заявки / role=user"},
        404: {"description": "Оффер не найден"},
        409: {"description": "Оффер уже выбран или отклонён"},
        422: {"description": "confirm должен быть true"},
    },
)
async def select(
    offer_id: UUID,
    body: OfferSelectRequest,
    current_user: UserOnly,
    db: DbSession,
    background_tasks: BackgroundTasks,
) -> OfferSelectResponse:
    if not body.confirm:
        from api.exceptions import InvalidStatusError
        raise InvalidStatusError("confirm must be true to select an offer")

    result = await select_offer(db, offer_id=offer_id, user_id=current_user.id)

    # Передаём UUID — к моменту BackgroundTask сессия уже закрыта
    _offer_id = result.offer.id

    async def _notify_service() -> None:
        async with AsyncSessionFactory() as notify_db:
            await notify_service_offer_selected(notify_db, offer_id=_offer_id)

    background_tasks.add_task(_notify_service)

    return OfferSelectResponse(
        offer_id=result.offer.id,
        status=result.offer.status,
        service_name=result.service_profile.name,
        service_phone=result.service_profile.phone,
    )
