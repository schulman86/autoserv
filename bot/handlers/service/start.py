"""
bot/handlers/service/start.py
───────────────────────────────
Обработчики /start и /help для автосервиса, навигация главного меню.

Сценарий /start:
    1. POST /auth/telegram (role=service) — idempotent get_or_create
    2. Попытка загрузить существующий профиль
    3a. Если профиля нет — предложить заполнить
    3b. Если профиль есть — показать главное меню
"""

from __future__ import annotations

import logging

import httpx
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.api_client import ApiClient
from bot.keyboards.service import back_to_service_menu_keyboard, service_main_menu_keyboard

logger = logging.getLogger(__name__)

router = Router(name="service:start")

HELP_TEXT = (
    "<b>❓ Помощь для автосервисов</b>\n\n"
    "<b>Как начать работу?</b>\n"
    "Заполните профиль: укажите название, районы работы и типы услуг. "
    "Без профиля заявки не будут к вам поступать.\n\n"
    "<b>Как найти заявки?</b>\n"
    "«Доступные заявки» — заявки в ваших районах со статусом не terminal.\n\n"
    "<b>Как отправить предложение?</b>\n"
    "Откройте заявку → «Отправить предложение» → укажите цену и детали.\n\n"
    "<b>История предложений:</b>\n"
    "«Мои предложения» — все ваши отклики с текущим статусом.\n\n"
    "<b>Поддержка:</b> обратитесь к администратору бота."
)


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Регистрация/приветствие автосервиса при /start."""
    assert message.from_user is not None

    await state.clear()

    telegram_id = message.from_user.id
    first_name = message.from_user.first_name or "автосервис"

    # 1. Регистрация (idempotent)
    try:
        async with ApiClient() as client:
            await client.auth_telegram(telegram_id=telegram_id, role="service")
    except httpx.HTTPStatusError as exc:
        logger.error("auth_telegram failed for service %s: %s", telegram_id, exc)
        await message.answer("⚠️ Сервис временно недоступен. Попробуйте позже.")
        return

    # 2. Проверяем наличие профиля
    profile_exists = False
    try:
        async with ApiClient(telegram_id=telegram_id) as client:
            profile = await client.get_my_service_profile()
        profile_exists = bool(profile.get("name"))
    except httpx.HTTPStatusError:
        # 404 — профиля ещё нет, это нормально
        profile_exists = False

    if not profile_exists:
        await message.answer(
            f"👋 Привет, <b>{first_name}</b>!\n\n"
            "Для начала работы необходимо заполнить профиль автосервиса. "
            "Это займёт около минуты.\n\n"
            "Нажмите кнопку ниже, чтобы начать:",
            reply_markup=service_main_menu_keyboard(),
        )
    else:
        await message.answer(
            f"👋 С возвращением, <b>{profile.get('name', first_name)}</b>!\n\n"
            "Выберите действие:",
            reply_markup=service_main_menu_keyboard(),
        )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, reply_markup=back_to_service_menu_keyboard())


# ── Callback: навигация главного меню ─────────────────────────────────────────

@router.callback_query(F.data == "svc:menu:main")
async def cb_main_menu(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(  # type: ignore[union-attr]
        "Выберите действие:",
        reply_markup=service_main_menu_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "svc:menu:help")
async def cb_help(call: CallbackQuery) -> None:
    await call.message.edit_text(  # type: ignore[union-attr]
        HELP_TEXT,
        reply_markup=back_to_service_menu_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "svc:menu:profile")
async def cb_start_profile(call: CallbackQuery, state: FSMContext) -> None:
    """Запустить FSM профиля через кнопку меню."""
    from bot.handlers.service.profile import start_profile_fsm
    await start_profile_fsm(call.message, state)  # type: ignore[arg-type]
    await call.answer()


@router.callback_query(F.data == "svc:menu:requests")
async def cb_available_requests(call: CallbackQuery) -> None:
    from bot.handlers.service.requests import show_available_requests
    await show_available_requests(call.message, call.from_user.id)  # type: ignore[union-attr, arg-type]
    await call.answer()


@router.callback_query(F.data == "svc:menu:my_offers")
async def cb_my_offers(call: CallbackQuery) -> None:
    from bot.handlers.service.offers import show_my_offers
    await show_my_offers(call.message, call.from_user.id)  # type: ignore[union-attr, arg-type]
    await call.answer()
