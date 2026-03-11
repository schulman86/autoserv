"""
bot/handlers/user/start.py
───────────────────────────
Обработчики команд /start и /help, а также главного меню пользователя.

Сценарий /start:
    1. POST /auth/telegram (role=user) — idempotent get_or_create
    2. Сохранить telegram_id в FSM-данных пользователя (не требуется — берётся из message)
    3. Показать приветствие + главное меню

Сценарий /help:
    Статичный FAQ-текст.
"""

from __future__ import annotations

import logging

import httpx
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.api_client import ApiClient
from bot.keyboards.user import back_to_menu_keyboard, main_menu_keyboard

logger = logging.getLogger(__name__)

router = Router(name="user:start")

HELP_TEXT = (
    "<b>❓ Помощь / FAQ</b>\n\n"
    "<b>Как создать заявку?</b>\n"
    "Нажмите «Создать заявку» в главном меню и следуйте подсказкам бота. "
    "Потребуется указать марку, модель, год авто, описание проблемы, "
    "район и удобное время.\n\n"
    "<b>Как найти мои заявки?</b>\n"
    "Нажмите «Мои заявки» — там отображаются все ваши обращения с количеством предложений.\n\n"
    "<b>Как выбрать автосервис?</b>\n"
    "Зайдите в нужную заявку → «Посмотреть предложения» → выберите подходящее.\n\n"
    "<b>Можно ли отменить заявку?</b>\n"
    "Да, если заявка ещё в статусе «создана» (нет принятых предложений).\n\n"
    "<b>Поддержка:</b> обратитесь к администратору бота."
)


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Регистрация/приветствие пользователя при /start."""
    assert message.from_user is not None  # polling гарантирует from_user

    await state.clear()  # Сбрасываем любое незавершённое FSM-состояние

    telegram_id = message.from_user.id
    first_name = message.from_user.first_name or "пользователь"

    try:
        # auth/telegram — открытый эндпоинт, telegram_id не нужен в заголовке
        async with ApiClient() as client:
            await client.auth_telegram(telegram_id=telegram_id, role="user")
    except httpx.HTTPStatusError as exc:
        logger.error("auth_telegram failed for %s: %s", telegram_id, exc)
        await message.answer(
            "⚠️ Сервис временно недоступен. Попробуйте позже.",
            reply_markup=None,
        )
        return

    await message.answer(
        f"👋 Привет, <b>{first_name}</b>!\n\n"
        "Я помогу вам найти подходящий автосервис. "
        "Создайте заявку — и сервисы сами предложат цены и время.\n\n"
        "Выберите действие:",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Статичный FAQ."""
    await message.answer(HELP_TEXT, reply_markup=back_to_menu_keyboard())


@router.message(Command("my_requests"))
async def cmd_my_requests(message: Message) -> None:
    """Шорткат — перенаправить на просмотр заявок через callback."""
    from bot.handlers.user.my_requests import show_my_requests  # избегаем circular import
    await show_my_requests(message)


# ── Callback: главное меню ───────────────────────────────────────────────────

@router.callback_query(F.data == "menu:main")
async def cb_main_menu(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text(  # type: ignore[union-attr]
        "Выберите действие:",
        reply_markup=main_menu_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "menu:help")
async def cb_help(call: CallbackQuery) -> None:
    await call.message.edit_text(  # type: ignore[union-attr]
        HELP_TEXT,
        reply_markup=back_to_menu_keyboard(),
    )
    await call.answer()


@router.callback_query(F.data == "menu:create_request")
async def cb_create_request(call: CallbackQuery, state: FSMContext) -> None:
    """Запускает FSM создания заявки через callback главного меню."""
    from bot.handlers.user.create_request import start_create_request  # избегаем circular import
    await start_create_request(call.message, state)  # type: ignore[arg-type]
    await call.answer()


@router.callback_query(F.data == "menu:my_requests")
async def cb_my_requests(call: CallbackQuery) -> None:
    from bot.handlers.user.my_requests import show_my_requests
    await show_my_requests(call.message)  # type: ignore[arg-type]
    await call.answer()
