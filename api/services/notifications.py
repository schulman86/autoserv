"""
api/services/notifications.py
───────────────────────────────
Сервис уведомлений: POST /internal/notify к боту.

Изменения v2:
  - Все notify_* принимают UUID вместо ORM-объектов (Fix: detached object в BackgroundTask)
  - notify_services_new_request: PostgreSQL && array overlap, SQLite — Python-фильтр
  - _send_notification: текст обрезается до 4000 символов (Telegram limit)
"""

from __future__ import annotations

import datetime
import logging
from uuid import UUID

import httpx
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.config import settings
from common.models.car_request import CarRequest
from common.models.offer import Offer
from common.models.service_profile import ServiceProfile
from common.models.user import User

logger = logging.getLogger(__name__)

_BOT_NOTIFY_TIMEOUT = 5.0
# Telegram API limit = 4096; держим запас
_TG_MAX_TEXT_LEN = 4000


async def _send_notification(telegram_id: int, text: str) -> None:
    """POST /internal/notify. Ошибки поглощаются — не блокируем основную операцию."""
    url = f"{settings.api_base_url.rstrip('/')}/internal/notify"
    payload = {"telegram_id": telegram_id, "text": text[:_TG_MAX_TEXT_LEN]}
    headers = {"X-Internal-Secret": settings.api_internal_secret}
    try:
        async with httpx.AsyncClient(timeout=_BOT_NOTIFY_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.warning(
                    "notifications: bot returned %s for telegram_id=%s: %s",
                    resp.status_code, telegram_id, resp.text[:200],
                )
            else:
                logger.debug("notifications: sent to telegram_id=%s", telegram_id)
    except httpx.TimeoutException:
        logger.warning("notifications: timeout telegram_id=%s url=%s", telegram_id, url)
    except httpx.RequestError as exc:
        logger.warning("notifications: request error telegram_id=%s: %s", telegram_id, exc)


def _dialect(db: AsyncSession) -> str:
    try:
        return db.bind.dialect.name  # type: ignore[union-attr]
    except Exception:
        return ""


async def notify_services_new_request(
    db: AsyncSession,
    *,
    request_id: UUID,
    area: str,
    car_brand: str,
    car_model: str,
    car_year: int,
    description: str,
    preferred_date: datetime.date,
    preferred_time: datetime.time,
) -> None:
    """
    Уведомить активные сервисы в `area` о новой заявке.
    Принимает примитивы (не ORM): безопасно вызывать из BackgroundTask.

    PostgreSQL: фильтр через && (ARRAY overlap, использует GIN-индекс → без N+1).
    SQLite (тесты): загружает активных сервисов, фильтрует в Python.
    """
    if _dialect(db) == "postgresql":
        from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
        result = await db.execute(
            select(ServiceProfile, User)
            .join(User, User.id == ServiceProfile.user_id)
            .where(ServiceProfile.is_active.is_(True))
            .where(
                ServiceProfile.areas.overlap(  # type: ignore[attr-defined]
                    sa.cast([area], PG_ARRAY(sa.Text))
                )
            )
        )
        matching = list(result.all())
    else:
        result = await db.execute(
            select(ServiceProfile, User)
            .join(User, User.id == ServiceProfile.user_id)
            .where(ServiceProfile.is_active.is_(True))
        )
        matching = [(sp, u) for sp, u in result.all() if area in sp.areas]

    if not matching:
        logger.debug("notifications: no services in area=%s request=%s", area, request_id)
        return

    text = (
        f"🔧 Новая заявка в районе «{area}»!\n\n"
        f"Автомобиль: {car_brand} {car_model} ({car_year})\n"
        f"Описание: {description[:200]}\n"
        f"Дата: {preferred_date.strftime('%d.%m.%Y')}, {preferred_time.strftime('%H:%M')}\n\n"
        f"Откликнитесь через бот!"
    )
    for _sp, user in matching:
        await _send_notification(user.telegram_id, text)
    logger.info("notifications: notified %d service(s) area=%s request=%s", len(matching), area, request_id)


async def notify_user_new_offer(db: AsyncSession, *, offer_id: UUID) -> None:
    """
    Уведомить владельца заявки о новом оффере.
    Загружает данные из переданной свежей сессии по offer_id.
    """
    offer_row = await db.execute(select(Offer).where(Offer.id == offer_id))
    offer = offer_row.scalar_one_or_none()
    if offer is None:
        logger.warning("notifications: offer %s not found", offer_id)
        return

    req_row = await db.execute(
        select(CarRequest, User)
        .join(User, User.id == CarRequest.user_id)
        .where(CarRequest.id == offer.request_id)
    )
    row = req_row.first()
    if row is None:
        logger.warning("notifications: request %s not found for offer %s", offer.request_id, offer_id)
        return
    _req, user = row

    sp_row = await db.execute(select(ServiceProfile).where(ServiceProfile.id == offer.service_id))
    sp = sp_row.scalar_one_or_none()
    service_name = sp.name if sp else "Автосервис"

    text = (
        f"💬 Новое предложение по вашей заявке!\n\n"
        f"Сервис: {service_name}\n"
        f"Цена: {offer.price:,.0f} ₽\n"
    )
    if offer.comment:
        text += f"Комментарий: {offer.comment[:200]}\n"
    if offer.proposed_date:
        text += f"Дата: {offer.proposed_date.strftime('%d.%m.%Y')}"
        if offer.proposed_time:
            text += f", {offer.proposed_time.strftime('%H:%M')}"
        text += "\n"
    text += "\nПросмотрите предложения в боте!"

    await _send_notification(user.telegram_id, text)
    logger.info("notifications: notified user telegram_id=%s offer=%s", user.telegram_id, offer_id)


async def notify_service_offer_selected(db: AsyncSession, *, offer_id: UUID) -> None:
    """
    Уведомить сервис о том, что его оффер выбран.
    Загружает данные из переданной свежей сессии по offer_id.
    """
    offer_row = await db.execute(select(Offer).where(Offer.id == offer_id))
    offer = offer_row.scalar_one_or_none()
    if offer is None:
        logger.warning("notifications: offer %s not found for selected notify", offer_id)
        return

    result = await db.execute(
        select(ServiceProfile, User)
        .join(User, User.id == ServiceProfile.user_id)
        .where(ServiceProfile.id == offer.service_id)
    )
    row = result.first()
    if row is None:
        logger.warning("notifications: service_profile %s not found offer=%s", offer.service_id, offer_id)
        return
    _sp, user = row

    req_row = await db.execute(select(CarRequest).where(CarRequest.id == offer.request_id))
    car_request = req_row.scalar_one_or_none()

    text = "🎉 Ваше предложение выбрано!\n\n"
    if car_request is not None:
        text += (
            f"Автомобиль: {car_request.car_brand} {car_request.car_model} ({car_request.car_year})\n"
            f"Район: {car_request.area}\n"
            f"Дата: {car_request.preferred_date.strftime('%d.%m.%Y')}, "
            f"{car_request.preferred_time.strftime('%H:%M')}\n\n"
        )
    text += "Свяжитесь с клиентом для подтверждения визита."

    await _send_notification(user.telegram_id, text)
    logger.info("notifications: notified service telegram_id=%s offer=%s", user.telegram_id, offer_id)
