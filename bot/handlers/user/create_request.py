"""
bot/handlers/user/create_request.py
──────────────────────────────────────
FSM-хендлеры для создания заявки на ремонт (CarRequestFSM, 8 шагов).

Шаги:
    1. car_brand   — марка (строка ≤100)
    2. car_model   — модель (строка ≤100)
    3. car_year    — год (1990–2030, только цифры)
    4. description — описание проблемы (≥10 символов)
    5. area        — район (кнопки из settings.allowed_areas)
    6. pref_date   — желаемая дата (ДД.ММ.ГГГГ, не в прошлом)
    7. pref_time   — желаемое время (ЧЧ:ММ)
    8. confirm     — подтверждение (inline Да/Нет)

После подтверждения вызывает POST /requests через ApiClient.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

import httpx
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.api_client import ApiClient
from bot.keyboards.user import (
    area_keyboard,
    back_to_menu_keyboard,
    confirm_keyboard,
    main_menu_keyboard,
)
from bot.states.user import CarRequestFSM
from common.config import settings

logger = logging.getLogger(__name__)

router = Router(name="user:create_request")

# Диапазон допустимых годов (синхронизировано со схемой)
YEAR_MIN = 1990
YEAR_MAX = 2030


# ── Точка входа в FSM ─────────────────────────────────────────────────────────

async def start_create_request(message: Message, state: FSMContext) -> None:
    """Начать FSM создания заявки. Вызывается из start.py и напрямую."""
    await state.clear()
    await state.set_state(CarRequestFSM.car_brand)
    await message.answer(
        "🚗 <b>Создание заявки — шаг 1/8</b>\n\n"
        "Введите <b>марку</b> автомобиля (например, Toyota):\n\n"
        "Или /cancel для отмены.",
    )


@router.message(F.text == "/cancel")
async def cmd_cancel_fsm(message: Message, state: FSMContext) -> None:
    """Отмена FSM из любого шага по команде /cancel."""
    current = await state.get_state()
    if current is None:
        await message.answer("Нечего отменять.", reply_markup=main_menu_keyboard())
        return
    await state.clear()
    await message.answer(
        "❌ Создание заявки отменено.",
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(F.data == "fsm:cancel")
async def cb_cancel_fsm(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(  # type: ignore[union-attr]
        "❌ Создание заявки отменено.",
        reply_markup=main_menu_keyboard(),
    )
    await call.answer()


# ── Шаг 1: марка ─────────────────────────────────────────────────────────────

@router.message(CarRequestFSM.car_brand)
async def step_car_brand(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text or len(text) > 100:
        await message.answer("⚠️ Марка не должна быть пустой и длиннее 100 символов. Повторите:")
        return
    await state.update_data(car_brand=text)
    await state.set_state(CarRequestFSM.car_model)
    await message.answer(
        "🚗 <b>Шаг 2/8</b>\n\nВведите <b>модель</b> автомобиля (например, Camry):"
    )


# ── Шаг 2: модель ────────────────────────────────────────────────────────────

@router.message(CarRequestFSM.car_model)
async def step_car_model(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text or len(text) > 100:
        await message.answer("⚠️ Модель не должна быть пустой и длиннее 100 символов. Повторите:")
        return
    await state.update_data(car_model=text)
    await state.set_state(CarRequestFSM.car_year)
    await message.answer(
        f"🚗 <b>Шаг 3/8</b>\n\nУкажите <b>год выпуска</b> ({YEAR_MIN}–{YEAR_MAX}):"
    )


# ── Шаг 3: год ───────────────────────────────────────────────────────────────

@router.message(CarRequestFSM.car_year)
async def step_car_year(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer(f"⚠️ Год — только цифры ({YEAR_MIN}–{YEAR_MAX}). Повторите:")
        return
    year = int(text)
    if not (YEAR_MIN <= year <= YEAR_MAX):
        await message.answer(f"⚠️ Год должен быть в диапазоне {YEAR_MIN}–{YEAR_MAX}. Повторите:")
        return
    await state.update_data(car_year=year)
    await state.set_state(CarRequestFSM.description)
    await message.answer(
        "🚗 <b>Шаг 4/8</b>\n\nОпишите <b>проблему</b> (минимум 10 символов):"
    )


# ── Шаг 4: описание ──────────────────────────────────────────────────────────

@router.message(CarRequestFSM.description)
async def step_description(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) < 10:
        await message.answer("⚠️ Описание слишком короткое — минимум 10 символов. Повторите:")
        return
    if len(text) > 2000:
        await message.answer("⚠️ Описание слишком длинное — максимум 2000 символов. Повторите:")
        return
    await state.update_data(description=text)
    await state.set_state(CarRequestFSM.area)
    await message.answer(
        "🚗 <b>Шаг 5/8</b>\n\nВыберите <b>район</b>:",
        reply_markup=area_keyboard(settings.allowed_areas),
    )


# ── Шаг 5: район (callback от кнопок) ────────────────────────────────────────

@router.callback_query(CarRequestFSM.area, F.data.startswith("area:"))
async def step_area(call: CallbackQuery, state: FSMContext) -> None:
    area = call.data.split(":", 1)[1]  # type: ignore[union-attr]
    if area not in settings.allowed_areas:
        await call.answer("⚠️ Неизвестный район. Выберите из списка.", show_alert=True)
        return
    await state.update_data(area=area)
    await state.set_state(CarRequestFSM.pref_date)
    await call.message.edit_text(  # type: ignore[union-attr]
        "🚗 <b>Шаг 6/8</b>\n\nВведите <b>желаемую дату</b> в формате ДД.ММ.ГГГГ\n"
        "(например, 25.03.2026):"
    )
    await call.answer()


# Защита: если пользователь ввёл текст вместо нажатия кнопки на шаге area
@router.message(CarRequestFSM.area)
async def step_area_text_guard(message: Message, state: FSMContext) -> None:
    await message.answer(
        "⚠️ Пожалуйста, выберите район из кнопок:",
        reply_markup=area_keyboard(settings.allowed_areas),
    )


# ── Шаг 6: дата ──────────────────────────────────────────────────────────────

@router.message(CarRequestFSM.pref_date)
async def step_pref_date(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    try:
        date = datetime.datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        await message.answer(
            "⚠️ Неверный формат даты. Введите в формате ДД.ММ.ГГГГ (например, 25.03.2026):"
        )
        return
    if date < datetime.date.today():
        await message.answer("⚠️ Дата не может быть в прошлом. Введите корректную дату:")
        return
    await state.update_data(preferred_date=date.isoformat())
    await state.set_state(CarRequestFSM.pref_time)
    await message.answer(
        "🚗 <b>Шаг 7/8</b>\n\nВведите <b>желаемое время</b> в формате ЧЧ:ММ\n"
        "(например, 14:30):"
    )


# ── Шаг 7: время ─────────────────────────────────────────────────────────────

@router.message(CarRequestFSM.pref_time)
async def step_pref_time(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    try:
        time = datetime.datetime.strptime(text, "%H:%M").time()
    except ValueError:
        await message.answer(
            "⚠️ Неверный формат времени. Введите в формате ЧЧ:ММ (например, 14:30):"
        )
        return
    await state.update_data(preferred_time=time.strftime("%H:%M:%S"))
    await state.set_state(CarRequestFSM.confirm)

    data = await state.get_data()
    summary = _format_summary(data)
    await message.answer(
        f"🚗 <b>Шаг 8/8 — Подтверждение</b>\n\n{summary}\n\nОтправить заявку?",
        reply_markup=confirm_keyboard(),
    )


def _format_summary(data: dict[str, Any]) -> str:
    return (
        f"🚘 <b>Автомобиль:</b> {data.get('car_brand')} {data.get('car_model')} "
        f"({data.get('car_year')})\n"
        f"📝 <b>Проблема:</b> {data.get('description')}\n"
        f"📍 <b>Район:</b> {data.get('area')}\n"
        f"📅 <b>Дата:</b> {data.get('preferred_date')}\n"
        f"🕐 <b>Время:</b> {data.get('preferred_time', '').rsplit(':', 1)[0]}"
    )


# ── Шаг 8: подтверждение ─────────────────────────────────────────────────────

@router.callback_query(CarRequestFSM.confirm, F.data == "confirm:yes")
async def step_confirm_yes(call: CallbackQuery, state: FSMContext) -> None:
    assert call.from_user is not None
    data = await state.get_data()

    payload = {
        "car_brand": data["car_brand"],
        "car_model": data["car_model"],
        "car_year": data["car_year"],
        "description": data["description"],
        "area": data["area"],
        "preferred_date": data["preferred_date"],
        "preferred_time": data["preferred_time"],
    }

    await state.clear()
    await call.answer()

    try:
        async with ApiClient(telegram_id=call.from_user.id) as client:
            response = await client.create_request(payload)
    except httpx.HTTPStatusError as exc:
        logger.error(
            "create_request failed for telegram_id=%s: %s", call.from_user.id, exc
        )
        await call.message.edit_text(  # type: ignore[union-attr]
            "⚠️ Не удалось отправить заявку. Попробуйте позже.",
            reply_markup=back_to_menu_keyboard(),
        )
        return

    await call.message.edit_text(  # type: ignore[union-attr]
        f"✅ <b>Заявка создана!</b>\n\n"
        f"Номер: <code>{response.get('id', '—')}</code>\n"
        f"Статус: {response.get('status', '—')}\n\n"
        "Сервисы уже получают вашу заявку. Уведомим, когда появятся предложения.",
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(CarRequestFSM.confirm, F.data == "confirm:no")
async def step_confirm_no(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(  # type: ignore[union-attr]
        "❌ Создание заявки отменено.",
        reply_markup=main_menu_keyboard(),
    )
    await call.answer()
