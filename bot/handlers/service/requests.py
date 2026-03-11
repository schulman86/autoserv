"""
bot/handlers/service/requests.py
──────────────────────────────────
Хендлеры просмотра доступных заявок для автосервиса.

Сценарии:
    - Список доступных заявок, отфильтрованных по районам профиля сервиса
    - Просмотр одной заявки с кнопкой «Отправить предложение»
"""

from __future__ import annotations

import logging

import httpx
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.api_client import ApiClient
from bot.keyboards.service import (
    available_requests_keyboard,
    back_to_service_menu_keyboard,
    request_view_keyboard,
    service_main_menu_keyboard,
)

logger = logging.getLogger(__name__)

router = Router(name="service:requests")

_NO_REQUESTS_TEXT = (
    "📭 Нет доступных заявок в ваших районах.\n\n"
    "Заявки появятся, когда пользователи создадут их в районах вашего обслуживания."
)


async def show_available_requests(message: Message, telegram_id: int) -> None:
    """
    Загрузить и показать список доступных заявок.
    Фильтрация по районам профиля происходит на стороне API.
    Переиспользуется из callback и прямых вызовов.
    """
    # Сначала получаем профиль, чтобы узнать районы
    try:
        async with ApiClient(telegram_id=telegram_id) as client:
            profile = await client.get_my_service_profile()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else 0
        if status_code == 404:
            await message.answer(
                "⚠️ Профиль не найден. Сначала заполните профиль.",
                reply_markup=service_main_menu_keyboard(),
            )
        else:
            logger.error("get_my_service_profile failed: %s", exc)
            await message.answer(
                "⚠️ Не удалось загрузить профиль. Попробуйте позже.",
                reply_markup=back_to_service_menu_keyboard(),
            )
        return

    areas: list[str] = profile.get("areas", [])
    if not areas:
        await message.answer(
            "⚠️ В профиле не указаны районы обслуживания. Обновите профиль.",
            reply_markup=service_main_menu_keyboard(),
        )
        return

    # Загружаем доступные заявки по первому (или всем) районам.
    # API GET /requests/available?area=X фильтрует по одному area.
    # Для MVP берём заявки из всех районов профиля и объединяем.
    all_requests: list[dict] = []
    seen_ids: set[str] = set()

    try:
        async with ApiClient(telegram_id=telegram_id) as client:
            for area in areas:
                reqs = await client.get_available_requests(area=area)
                for req in reqs:
                    req_id = str(req.get("id", ""))
                    if req_id and req_id not in seen_ids:
                        seen_ids.add(req_id)
                        all_requests.append(req)
    except httpx.HTTPStatusError as exc:
        logger.error("get_available_requests failed: %s", exc)
        await message.answer(
            "⚠️ Не удалось загрузить заявки. Попробуйте позже.",
            reply_markup=back_to_service_menu_keyboard(),
        )
        return

    if not all_requests:
        await message.answer(_NO_REQUESTS_TEXT, reply_markup=back_to_service_menu_keyboard())
        return

    await message.answer(
        f"🔍 <b>Доступные заявки</b> ({len(all_requests)} шт.):",
        reply_markup=available_requests_keyboard(all_requests),
    )


# ── Просмотр одной заявки ─────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("svc:req:view:"))
async def cb_view_request(call: CallbackQuery) -> None:
    assert call.from_user is not None
    request_id = call.data.split(":", 3)[3]  # type: ignore[union-attr]

    # Нет отдельного эндпоинта GET /requests/{id} — получаем список и ищем
    try:
        async with ApiClient(telegram_id=call.from_user.id) as client:
            profile = await client.get_my_service_profile()
            areas = profile.get("areas", [])
            all_requests: list[dict] = []
            seen: set[str] = set()
            for area in areas:
                for req in await client.get_available_requests(area=area):
                    rid = str(req.get("id", ""))
                    if rid and rid not in seen:
                        seen.add(rid)
                        all_requests.append(req)
    except httpx.HTTPStatusError as exc:
        logger.error("cb_view_request failed: %s", exc)
        await call.answer("⚠️ Ошибка загрузки. Попробуйте позже.", show_alert=True)
        return

    req = next((r for r in all_requests if str(r.get("id")) == request_id), None)
    if req is None:
        await call.answer("⚠️ Заявка не найдена или уже закрыта.", show_alert=True)
        return

    pref_date = req.get("preferred_date", "—")
    pref_time = str(req.get("preferred_time", "—"))[:5]  # HH:MM из HH:MM:SS
    text = (
        f"🚗 <b>{req['car_brand']} {req['car_model']} ({req['car_year']})</b>\n"
        f"📝 {req.get('description', '—')}\n"
        f"📍 Район: <b>{req.get('area', '—')}</b>\n"
        f"📅 Дата: {pref_date} в {pref_time}\n"
        f"📊 Статус: {req.get('status', '—')}"
    )
    await call.message.edit_text(  # type: ignore[union-attr]
        text,
        reply_markup=request_view_keyboard(request_id),
    )
    await call.answer()
