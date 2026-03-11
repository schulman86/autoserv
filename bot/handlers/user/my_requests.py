"""
bot/handlers/user/my_requests.py
──────────────────────────────────
Хендлеры для просмотра и управления заявками пользователя.

Сценарии:
    - Показать список заявок (GET /requests/my)
    - Просмотр одной заявки с кнопками действий
    - Отмена заявки (PATCH /requests/{id}/cancel)
"""

from __future__ import annotations

import logging

import httpx
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.api_client import ApiClient
from bot.keyboards.user import (
    back_to_menu_keyboard,
    cancel_confirm_keyboard,
    my_requests_keyboard,
    request_detail_keyboard,
)

logger = logging.getLogger(__name__)

router = Router(name="user:my_requests")

_NO_REQUESTS_TEXT = (
    "📂 У вас пока нет заявок.\n\n"
    "Нажмите «Создать заявку» в главном меню, чтобы найти автосервис."
)


async def show_my_requests(message: Message) -> None:
    """
    Загрузить и отобразить список заявок текущего пользователя.
    Переиспользуется из callback и команды /my_requests.
    """
    assert message.from_user is not None

    try:
        async with ApiClient(telegram_id=message.from_user.id) as client:
            requests = await client.get_my_requests(telegram_id=message.from_user.id)
    except httpx.HTTPStatusError as exc:
        logger.error("get_my_requests failed: %s", exc)
        await message.answer(
            "⚠️ Не удалось загрузить заявки. Попробуйте позже.",
            reply_markup=back_to_menu_keyboard(),
        )
        return

    if not requests:
        await message.answer(_NO_REQUESTS_TEXT, reply_markup=back_to_menu_keyboard())
        return

    await message.answer(
        f"📂 <b>Мои заявки</b> ({len(requests)} шт.):",
        reply_markup=my_requests_keyboard(requests),
    )


# ── Просмотр одной заявки ────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("request:view:"))
async def cb_view_request(call: CallbackQuery) -> None:
    request_id = call.data.split(":", 2)[2]  # type: ignore[union-attr]
    assert call.from_user is not None

    try:
        async with ApiClient(telegram_id=call.from_user.id) as client:
            requests = await client.get_my_requests(telegram_id=call.from_user.id)
    except httpx.HTTPStatusError as exc:
        logger.error("get_my_requests failed in view: %s", exc)
        await call.answer("⚠️ Ошибка загрузки. Попробуйте позже.", show_alert=True)
        return

    req = next((r for r in requests if str(r.get("id")) == request_id), None)
    if req is None:
        await call.answer("⚠️ Заявка не найдена.", show_alert=True)
        return

    text = (
        f"🚘 <b>{req['car_brand']} {req['car_model']} ({req['car_year']})</b>\n"
        f"📍 Район: {req.get('area', '—')}\n"
        f"📊 Статус: <b>{req['status']}</b>\n"
        f"📨 Предложений: <b>{req.get('offers_count', 0)}</b>"
    )
    await call.message.edit_text(  # type: ignore[union-attr]
        text,
        reply_markup=request_detail_keyboard(request_id, req["status"]),
    )
    await call.answer()


# ── Отмена заявки ─────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("request:cancel:"))
async def cb_cancel_request_prompt(call: CallbackQuery) -> None:
    """Спросить подтверждение перед отменой."""
    request_id = call.data.split(":", 2)[2]  # type: ignore[union-attr]
    await call.message.edit_text(  # type: ignore[union-attr]
        "❓ Вы уверены, что хотите отменить заявку? Это действие необратимо.",
        reply_markup=cancel_confirm_keyboard(request_id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("request:cancel_confirmed:"))
async def cb_cancel_request_confirmed(call: CallbackQuery) -> None:
    """Выполнить отмену после подтверждения."""
    request_id = call.data.split(":", 2)[2]  # type: ignore[union-attr]

    try:
        async with ApiClient(telegram_id=call.from_user.id) as client:
            await client.cancel_request(request_id=request_id)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else 0
        if status_code == 422:
            msg = "⚠️ Заявку нельзя отменить: она уже не в статусе «создана»."
        elif status_code == 403:
            msg = "⚠️ Это не ваша заявка."
        elif status_code == 404:
            msg = "⚠️ Заявка не найдена."
        else:
            msg = "⚠️ Не удалось отменить заявку. Попробуйте позже."
        await call.answer(msg, show_alert=True)
        return

    await call.message.edit_text(  # type: ignore[union-attr]
        "✅ Заявка успешно отменена.",
        reply_markup=back_to_menu_keyboard(),
    )
    await call.answer()
