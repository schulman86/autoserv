"""
bot/handlers/service/profile.py
─────────────────────────────────
FSM-хендлеры для заполнения/обновления профиля автосервиса (ServiceProfileFSM).

Шаги:
    1. name        — название (строка ≤200)
    2. description — описание (опционально, /skip)
    3. areas       — районы (toggle inline-кнопки, множественный выбор)
    4. services    — типы услуг (toggle inline-кнопки, множественный выбор)
    5. phone       — телефон в формате +7XXXXXXXXXX
    6. confirm     — подтверждение (inline Сохранить/Отмена)

После подтверждения вызывает POST /service-profile (upsert) через ApiClient.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.api_client import ApiClient
from bot.keyboards.service import (
    DEFAULT_SERVICES,
    areas_select_keyboard,
    back_to_service_menu_keyboard,
    profile_confirm_keyboard,
    service_main_menu_keyboard,
    services_select_keyboard,
)
from bot.states.service import ServiceProfileFSM
from common.config import settings

logger = logging.getLogger(__name__)

router = Router(name="service:profile")

PHONE_RE = re.compile(r"^\+7\d{10}$")


# ── Точка входа в FSM ─────────────────────────────────────────────────────────

async def start_profile_fsm(message: Message, state: FSMContext) -> None:
    """Начать FSM заполнения профиля. Вызывается из start.py."""
    await state.clear()
    await state.set_state(ServiceProfileFSM.name)
    await message.answer(
        "🏪 <b>Заполнение профиля — шаг 1/6</b>\n\n"
        "Введите <b>название</b> вашего автосервиса:\n\n"
        "Или /cancel для отмены.",
    )


@router.message(F.text == "/cancel")
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await message.answer("Нечего отменять.", reply_markup=service_main_menu_keyboard())
        return
    await state.clear()
    await message.answer("❌ Заполнение профиля отменено.", reply_markup=service_main_menu_keyboard())


@router.callback_query(F.data == "svc:fsm_cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(  # type: ignore[union-attr]
        "❌ Действие отменено.",
        reply_markup=service_main_menu_keyboard(),
    )
    await call.answer()


# ── Шаг 1: название ──────────────────────────────────────────────────────────

@router.message(ServiceProfileFSM.name)
async def step_name(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text or len(text) > 200:
        await message.answer("⚠️ Название не должно быть пустым и длиннее 200 символов. Повторите:")
        return
    await state.update_data(name=text)
    await state.set_state(ServiceProfileFSM.description)
    await message.answer(
        "🏪 <b>Шаг 2/6</b>\n\n"
        "Введите <b>описание</b> автосервиса (опционально).\n"
        "Или отправьте /skip, чтобы пропустить."
    )


# ── Шаг 2: описание ───────────────────────────────────────────────────────────

@router.message(ServiceProfileFSM.description, F.text == "/skip")
async def step_description_skip(message: Message, state: FSMContext) -> None:
    await state.update_data(description=None)
    await _go_to_areas(message, state)


@router.message(ServiceProfileFSM.description)
async def step_description(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) > 2000:
        await message.answer("⚠️ Описание слишком длинное — максимум 2000 символов. Повторите:")
        return
    await state.update_data(description=text or None)
    await _go_to_areas(message, state)


async def _go_to_areas(message: Message, state: FSMContext) -> None:
    await state.update_data(selected_areas=[])
    await state.set_state(ServiceProfileFSM.areas)
    await message.answer(
        "🏪 <b>Шаг 3/6</b>\n\n"
        "Выберите <b>районы</b> обслуживания (можно несколько).\n"
        "Нажмите ➡️ Далее когда выберете все нужные:",
        reply_markup=areas_select_keyboard(settings.allowed_areas, selected=set()),
    )


# ── Шаг 3: районы (toggle callbacks) ─────────────────────────────────────────

@router.callback_query(ServiceProfileFSM.areas, F.data.startswith("svc:area_toggle:"))
async def cb_area_toggle(call: CallbackQuery, state: FSMContext) -> None:
    area = call.data.split(":", 2)[2]  # type: ignore[union-attr]
    if area not in settings.allowed_areas:
        await call.answer("⚠️ Неизвестный район.", show_alert=True)
        return

    data = await state.get_data()
    selected: set[str] = set(data.get("selected_areas", []))
    if area in selected:
        selected.discard(area)
    else:
        selected.add(area)
    await state.update_data(selected_areas=list(selected))

    await call.message.edit_reply_markup(  # type: ignore[union-attr]
        reply_markup=areas_select_keyboard(settings.allowed_areas, selected=selected)
    )
    await call.answer()


@router.callback_query(ServiceProfileFSM.areas, F.data == "svc:areas_done")
async def cb_areas_done(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected: list[str] = data.get("selected_areas", [])
    if not selected:
        await call.answer("⚠️ Выберите хотя бы один район.", show_alert=True)
        return

    await state.update_data(selected_services=[])
    await state.set_state(ServiceProfileFSM.services)
    await call.message.edit_text(  # type: ignore[union-attr]
        "🏪 <b>Шаг 4/6</b>\n\n"
        "Выберите <b>типы услуг</b> (можно несколько).\n"
        "Нажмите ➡️ Далее когда выберете все нужные:",
        reply_markup=services_select_keyboard(DEFAULT_SERVICES, selected=set()),
    )
    await call.answer()


# ── Шаг 4: услуги (toggle callbacks) ─────────────────────────────────────────

@router.callback_query(ServiceProfileFSM.services, F.data.startswith("svc:svc_toggle:"))
async def cb_service_toggle(call: CallbackQuery, state: FSMContext) -> None:
    svc = call.data.split(":", 2)[2]  # type: ignore[union-attr]
    if svc not in DEFAULT_SERVICES:
        await call.answer("⚠️ Неизвестный тип услуги.", show_alert=True)
        return

    data = await state.get_data()
    selected: set[str] = set(data.get("selected_services", []))
    if svc in selected:
        selected.discard(svc)
    else:
        selected.add(svc)
    await state.update_data(selected_services=list(selected))

    await call.message.edit_reply_markup(  # type: ignore[union-attr]
        reply_markup=services_select_keyboard(DEFAULT_SERVICES, selected=selected)
    )
    await call.answer()


@router.callback_query(ServiceProfileFSM.services, F.data == "svc:services_done")
async def cb_services_done(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected: list[str] = data.get("selected_services", [])
    if not selected:
        await call.answer("⚠️ Выберите хотя бы один тип услуги.", show_alert=True)
        return

    await state.set_state(ServiceProfileFSM.phone)
    await call.message.edit_text(  # type: ignore[union-attr]
        "🏪 <b>Шаг 5/6</b>\n\n"
        "Введите <b>контактный телефон</b> в формате <code>+7XXXXXXXXXX</code>:"
    )
    await call.answer()


# ── Шаг 5: телефон ────────────────────────────────────────────────────────────

@router.message(ServiceProfileFSM.phone)
async def step_phone(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not PHONE_RE.match(text):
        await message.answer(
            "⚠️ Неверный формат телефона. Введите в формате <code>+7XXXXXXXXXX</code> "
            "(11 цифр после +7):"
        )
        return
    await state.update_data(phone=text)
    await state.set_state(ServiceProfileFSM.confirm)

    data = await state.get_data()
    summary = _format_profile_summary(data)
    await message.answer(
        f"🏪 <b>Шаг 6/6 — Подтверждение</b>\n\n{summary}\n\nСохранить профиль?",
        reply_markup=profile_confirm_keyboard(),
    )


def _format_profile_summary(data: dict[str, Any]) -> str:
    areas = ", ".join(data.get("selected_areas", []))
    services = ", ".join(data.get("selected_services", []))
    description = data.get("description") or "<i>не указано</i>"
    return (
        f"🏪 <b>Название:</b> {data.get('name')}\n"
        f"📝 <b>Описание:</b> {description}\n"
        f"📍 <b>Районы:</b> {areas}\n"
        f"🔧 <b>Услуги:</b> {services}\n"
        f"📞 <b>Телефон:</b> {data.get('phone')}"
    )


# ── Шаг 6: подтверждение ──────────────────────────────────────────────────────

@router.callback_query(ServiceProfileFSM.confirm, F.data == "svc:profile_confirm:yes")
async def cb_profile_confirm_yes(call: CallbackQuery, state: FSMContext) -> None:
    assert call.from_user is not None
    data = await state.get_data()

    payload = {
        "name": data["name"],
        "description": data.get("description"),
        "areas": data["selected_areas"],
        "services": data["selected_services"],
        "phone": data["phone"],
    }

    await state.clear()
    await call.answer()

    try:
        async with ApiClient(telegram_id=call.from_user.id) as client:
            await client.upsert_service_profile(payload=payload)
    except httpx.HTTPStatusError as exc:
        logger.error("upsert_service_profile failed for %s: %s", call.from_user.id, exc)
        await call.message.edit_text(  # type: ignore[union-attr]
            "⚠️ Не удалось сохранить профиль. Попробуйте позже.",
            reply_markup=back_to_service_menu_keyboard(),
        )
        return

    await call.message.edit_text(  # type: ignore[union-attr]
        "✅ <b>Профиль успешно сохранён!</b>\n\n"
        "Теперь вы будете получать уведомления о новых заявках в ваших районах.",
        reply_markup=service_main_menu_keyboard(),
    )


@router.callback_query(ServiceProfileFSM.confirm, F.data == "svc:profile_confirm:no")
async def cb_profile_confirm_no(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(  # type: ignore[union-attr]
        "❌ Сохранение профиля отменено.",
        reply_markup=service_main_menu_keyboard(),
    )
    await call.answer()
