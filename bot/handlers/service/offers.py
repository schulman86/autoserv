"""
bot/handlers/service/offers.py
────────────────────────────────
Хендлеры для создания предложений (OfferFSM) и просмотра истории откликов.

OfferFSM шаги:
    1. price         — стоимость (число > 0)
    2. comment       — комментарий (опционально, /skip)
    3. proposed_date — альтернативная дата (ДД.ММ.ГГГГ, опционально, кнопка пропустить)
    4. proposed_time — альтернативное время (ЧЧ:ММ, опционально, кнопка пропустить)
    5. confirm       — подтверждение → POST /offers

Push «Вас выбрали»: сюда приходит уведомление из bot/handlers/internal.py
через send_message — отдельной логики в хендлере не требуется.
"""

from __future__ import annotations

import datetime
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.api_client import ApiClient
from bot.keyboards.service import (
    back_to_service_menu_keyboard,
    my_offers_keyboard,
    offer_confirm_keyboard,
    offer_date_keyboard,
    offer_time_keyboard,
    service_main_menu_keyboard,
)
from bot.states.service import OfferFSM

logger = logging.getLogger(__name__)

router = Router(name="service:offers")


# ── История предложений ───────────────────────────────────────────────────────

async def show_my_offers(message: Message, telegram_id: int) -> None:
    """
    Показать историю откликов сервиса.
    Переиспользуется из callback и прямых вызовов.
    """
    try:
        async with ApiClient(telegram_id=telegram_id) as client:
            offers = await client.get_my_offers()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else 0
        if status_code == 404:
            await message.answer(
                "⚠️ Профиль не найден. Сначала заполните профиль.",
                reply_markup=service_main_menu_keyboard(),
            )
        else:
            logger.error("get_my_offers failed: %s", exc)
            await message.answer(
                "⚠️ Не удалось загрузить предложения. Попробуйте позже.",
                reply_markup=back_to_service_menu_keyboard(),
            )
        return

    if not offers:
        await message.answer(
            "📁 У вас пока нет предложений.\n\n"
            "Найдите доступную заявку и отправьте предложение.",
            reply_markup=back_to_service_menu_keyboard(),
        )
        return

    await message.answer(
        f"📁 <b>Мои предложения</b> ({len(offers)} шт.):",
        reply_markup=my_offers_keyboard(offers),
    )


@router.callback_query(F.data.startswith("svc:offer:detail:"))
async def cb_offer_detail(call: CallbackQuery) -> None:
    """Заглушка: детальный просмотр оффера — показываем статус."""
    await call.answer("Детали предложения пока недоступны.", show_alert=False)


# ── Запуск OfferFSM ───────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("svc:offer:start:"))
async def cb_start_offer(call: CallbackQuery, state: FSMContext) -> None:
    """Начать FSM создания оффера по конкретной заявке."""
    request_id = call.data.split(":", 3)[3]  # type: ignore[union-attr]
    await state.clear()
    await state.update_data(request_id=request_id)
    await state.set_state(OfferFSM.price)
    await call.message.edit_text(  # type: ignore[union-attr]
        "📨 <b>Создание предложения — шаг 1/5</b>\n\n"
        "Введите <b>стоимость работ</b> в рублях (например, 4500):\n\n"
        "Или /cancel для отмены.",
    )
    await call.answer()


# ── Шаг 1: цена ───────────────────────────────────────────────────────────────

@router.message(OfferFSM.price)
async def step_price(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip().replace(",", ".")
    try:
        price = Decimal(text)
        if price <= 0:
            raise ValueError
    except (InvalidOperation, ValueError):
        await message.answer("⚠️ Введите корректную сумму (число больше 0, например 4500):")
        return
    await state.update_data(price=str(price))
    await state.set_state(OfferFSM.comment)
    await message.answer(
        "📨 <b>Шаг 2/5</b>\n\n"
        "Введите <b>комментарий</b> к предложению (опционально).\n"
        "Или отправьте /skip, чтобы пропустить."
    )


# ── Шаг 2: комментарий ────────────────────────────────────────────────────────

@router.message(OfferFSM.comment, F.text == "/skip")
async def step_comment_skip(message: Message, state: FSMContext) -> None:
    await state.update_data(comment=None)
    await _go_to_proposed_date(message, state)


@router.message(OfferFSM.comment)
async def step_comment(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) > 1000:
        await message.answer("⚠️ Комментарий слишком длинный — максимум 1000 символов. Повторите:")
        return
    await state.update_data(comment=text or None)
    await _go_to_proposed_date(message, state)


async def _go_to_proposed_date(message: Message, state: FSMContext) -> None:
    await state.set_state(OfferFSM.proposed_date)
    await message.answer(
        "📨 <b>Шаг 3/5</b>\n\n"
        "Укажите <b>альтернативную дату</b> (ДД.ММ.ГГГГ) если не подходит дата из заявки.\n"
        "Или нажмите кнопку пропустить:",
        reply_markup=offer_date_keyboard(),
    )


# ── Шаг 3: альтернативная дата ────────────────────────────────────────────────

@router.callback_query(OfferFSM.proposed_date, F.data == "svc:offer:skip_date")
async def cb_skip_date(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(proposed_date=None)
    await _go_to_proposed_time(call.message, state)  # type: ignore[arg-type]
    await call.answer()


@router.message(OfferFSM.proposed_date)
async def step_proposed_date(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    try:
        date = datetime.datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        await message.answer(
            "⚠️ Неверный формат даты. Введите ДД.ММ.ГГГГ (например, 25.03.2026)\n"
            "или нажмите кнопку «Пропустить»:",
            reply_markup=offer_date_keyboard(),
        )
        return
    if date < datetime.date.today():
        await message.answer(
            "⚠️ Дата не может быть в прошлом. Повторите:",
            reply_markup=offer_date_keyboard(),
        )
        return
    await state.update_data(proposed_date=date.isoformat())
    await _go_to_proposed_time(message, state)


async def _go_to_proposed_time(message: Message, state: FSMContext) -> None:
    await state.set_state(OfferFSM.proposed_time)
    await message.answer(
        "📨 <b>Шаг 4/5</b>\n\n"
        "Укажите <b>альтернативное время</b> (ЧЧ:ММ) если не подходит время из заявки.\n"
        "Или нажмите кнопку пропустить:",
        reply_markup=offer_time_keyboard(),
    )


# ── Шаг 4: альтернативное время ───────────────────────────────────────────────

@router.callback_query(OfferFSM.proposed_time, F.data == "svc:offer:skip_time")
async def cb_skip_time(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(proposed_time=None)
    await _go_to_confirm(call.message, state)  # type: ignore[arg-type]
    await call.answer()


@router.message(OfferFSM.proposed_time)
async def step_proposed_time(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    try:
        time = datetime.datetime.strptime(text, "%H:%M").time()
    except ValueError:
        await message.answer(
            "⚠️ Неверный формат времени. Введите ЧЧ:ММ (например, 14:30)\n"
            "или нажмите кнопку «Пропустить»:",
            reply_markup=offer_time_keyboard(),
        )
        return
    await state.update_data(proposed_time=time.strftime("%H:%M:%S"))
    await _go_to_confirm(message, state)


async def _go_to_confirm(message: Message, state: FSMContext) -> None:
    await state.set_state(OfferFSM.confirm)
    data = await state.get_data()
    summary = _format_offer_summary(data)
    await message.answer(
        f"📨 <b>Шаг 5/5 — Подтверждение</b>\n\n{summary}\n\nОтправить предложение?",
        reply_markup=offer_confirm_keyboard(),
    )


def _format_offer_summary(data: dict[str, Any]) -> str:
    comment = data.get("comment") or "<i>не указан</i>"
    proposed_date = data.get("proposed_date") or "<i>из заявки</i>"
    proposed_time = data.get("proposed_time")
    if proposed_time:
        proposed_time = proposed_time[:5]  # HH:MM
    else:
        proposed_time = "<i>из заявки</i>"
    return (
        f"💰 <b>Стоимость:</b> {data.get('price')} ₽\n"
        f"💬 <b>Комментарий:</b> {comment}\n"
        f"📅 <b>Дата:</b> {proposed_date}\n"
        f"🕐 <b>Время:</b> {proposed_time}"
    )


# ── Шаг 5: подтверждение ──────────────────────────────────────────────────────

@router.callback_query(OfferFSM.confirm, F.data == "svc:offer_confirm:yes")
async def cb_offer_confirm_yes(call: CallbackQuery, state: FSMContext) -> None:
    assert call.from_user is not None
    data = await state.get_data()

    payload: dict[str, Any] = {
        "request_id": data["request_id"],
        "price": data["price"],
        "comment": data.get("comment"),
        "proposed_date": data.get("proposed_date"),
        "proposed_time": data.get("proposed_time"),
    }

    await state.clear()
    await call.answer()

    try:
        async with ApiClient(telegram_id=call.from_user.id) as client:
            await client.create_offer(payload=payload)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else 0
        if status_code == 409:
            msg = "⚠️ Вы уже отправили предложение по этой заявке."
        elif status_code == 422:
            msg = "⚠️ Заявка уже закрыта и не принимает предложения."
        else:
            logger.error("create_offer failed for %s: %s", call.from_user.id, exc)
            msg = "⚠️ Не удалось отправить предложение. Попробуйте позже."
        await call.message.edit_text(  # type: ignore[union-attr]
            msg,
            reply_markup=back_to_service_menu_keyboard(),
        )
        return

    await call.message.edit_text(  # type: ignore[union-attr]
        "✅ <b>Предложение отправлено!</b>\n\n"
        "Пользователь получит уведомление и сможет выбрать вашу кандидатуру.\n\n"
        "Если вас выберут — вы получите уведомление здесь.",
        reply_markup=service_main_menu_keyboard(),
    )


@router.callback_query(OfferFSM.confirm, F.data == "svc:offer_confirm:no")
async def cb_offer_confirm_no(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(  # type: ignore[union-attr]
        "❌ Создание предложения отменено.",
        reply_markup=service_main_menu_keyboard(),
    )
    await call.answer()
