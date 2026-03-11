"""
bot/handlers/user/offers.py
─────────────────────────────
Хендлеры для просмотра и выбора предложений (офферов) по заявке.

Сценарии:
    - Показать список предложений по заявке (GET /offers/by-request/{id})
    - Выбрать предложение (PATCH /offers/{id}/select)

Показывается до 10 предложений согласно Definition of Done 3.1.
"""

from __future__ import annotations

import logging

import httpx
from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.api_client import ApiClient
from bot.keyboards.user import (
    back_to_menu_keyboard,
    offer_select_confirm_keyboard,
    offers_keyboard,
)

logger = logging.getLogger(__name__)

router = Router(name="user:offers")


# ── Список предложений ────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("request:offers:"))
async def cb_view_offers(call: CallbackQuery) -> None:
    request_id = call.data.split(":", 2)[2]  # type: ignore[union-attr]

    try:
        async with ApiClient(telegram_id=call.from_user.id) as client:
            offers = await client.get_offers_by_request(request_id=request_id)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else 0
        if status_code == 403:
            await call.answer("⚠️ Это не ваша заявка.", show_alert=True)
        elif status_code == 404:
            await call.answer("⚠️ Заявка не найдена.", show_alert=True)
        else:
            logger.error("get_offers_by_request failed: %s", exc)
            await call.answer("⚠️ Ошибка загрузки. Попробуйте позже.", show_alert=True)
        return

    if not offers:
        await call.message.edit_text(  # type: ignore[union-attr]
            "📭 Предложений пока нет. Сервисы скоро откликнутся!",
            reply_markup=back_to_menu_keyboard(),
        )
        await call.answer()
        return

    text = f"📨 <b>Предложения</b> ({min(len(offers), 10)} из {len(offers)}):"
    await call.message.edit_text(  # type: ignore[union-attr]
        text,
        reply_markup=offers_keyboard(offers, request_id),
    )
    await call.answer()


# ── Выбор предложения ─────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("offer:select:"))
async def cb_offer_select_prompt(call: CallbackQuery) -> None:
    """Спросить подтверждение перед выбором оффера."""
    offer_id = call.data.split(":", 2)[2]  # type: ignore[union-attr]
    await call.message.edit_text(  # type: ignore[union-attr]
        "❓ Подтвердите выбор автосервиса. После подтверждения "
        "остальные предложения будут отклонены.",
        reply_markup=offer_select_confirm_keyboard(offer_id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("offer:select_confirmed:"))
async def cb_offer_select_confirmed(call: CallbackQuery) -> None:
    """Выполнить выбор оффера после подтверждения."""
    offer_id = call.data.split(":", 2)[2]  # type: ignore[union-attr]

    try:
        async with ApiClient(telegram_id=call.from_user.id) as client:
            result = await client.select_offer(offer_id=offer_id)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else 0
        if status_code == 409:
            msg = "⚠️ Предложение уже выбрано или недоступно."
        elif status_code == 403:
            msg = "⚠️ Недостаточно прав."
        elif status_code == 404:
            msg = "⚠️ Предложение не найдено."
        else:
            logger.error("select_offer failed: %s", exc)
            msg = "⚠️ Не удалось выбрать предложение. Попробуйте позже."
        await call.answer(msg, show_alert=True)
        return

    service_name = result.get("service_name", "—")
    service_phone = result.get("service_phone", "—")

    await call.message.edit_text(  # type: ignore[union-attr]
        f"✅ <b>Вы выбрали автосервис!</b>\n\n"
        f"🏪 <b>{service_name}</b>\n"
        f"📞 Телефон: <b>{service_phone}</b>\n\n"
        "Сервис получил уведомление и свяжется с вами.",
        reply_markup=back_to_menu_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "offer:select_cancel")
async def cb_offer_select_cancel(call: CallbackQuery) -> None:
    await call.message.edit_text(  # type: ignore[union-attr]
        "Выбор отменён.",
        reply_markup=back_to_menu_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "offer:noop")
async def cb_offer_noop(call: CallbackQuery) -> None:
    """Обработчик для кнопок уже выбранных/отклонённых офферов."""
    await call.answer("Это предложение уже не активно.", show_alert=False)
