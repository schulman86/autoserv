"""
bot/utils/sender.py
────────────────────
Утилита для отправки Telegram-сообщений конкретному пользователю.

Используется из bot/handlers/internal.py (приём POST /internal/notify от API)
и из будущих bot/handlers/service.py, bot/handlers/user.py для push-уведомлений
в контексте FSM.

Принцип:
    - Тонкая обёртка над Bot.send_message — не содержит бизнес-логики.
    - Ошибки (TelegramForbiddenError, TelegramBadRequest) логируются и НЕ
      пробрасываются: недоставленное уведомление не должно ломать основной поток.
    - Пользователь мог заблокировать бота — это нормальная ситуация.

Использование в handlers:
    from bot.utils.sender import send_message

    async def notify(bot: Bot, telegram_id: int, text: str) -> None:
        await send_message(bot, telegram_id=telegram_id, text=text)
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

logger = logging.getLogger(__name__)


async def send_message(
    bot: Bot,
    *,
    telegram_id: int,
    text: str,
    parse_mode: str | None = None,
) -> bool:
    """
    Отправить Telegram-сообщение пользователю по telegram_id.

    Исключения поглощаются и логируются — функция не бросает.
    Это намеренное поведение: уведомления вторичны по отношению к
    бизнес-операциям, их потеря допустима.

    Args:
        bot:         Инициализированный экземпляр aiogram.Bot
        telegram_id: Telegram user ID получателя
        text:        Текст сообщения (plain text или HTML, в зависимости от parse_mode)
        parse_mode:  "HTML" | "Markdown" | None (None = plain text)

    Returns:
        True  — сообщение доставлено
        False — доставка не удалась (ошибка залогирована)
    """
    try:
        await bot.send_message(
            chat_id=telegram_id,
            text=text,
            parse_mode=parse_mode,
        )
        logger.debug("sender: delivered message to telegram_id=%s", telegram_id)
        return True

    except TelegramForbiddenError:
        # Пользователь заблокировал бота — обычная ситуация
        logger.info(
            "sender: telegram_id=%s blocked the bot, skipping notification",
            telegram_id,
        )
        return False

    except TelegramBadRequest as exc:
        # Некорректный запрос (напр. слишком длинный текст, неверный parse_mode)
        logger.warning(
            "sender: bad request for telegram_id=%s: %s",
            telegram_id, exc,
        )
        return False

    except Exception as exc:
        # Сеть недоступна, Telegram API недоступен и т.п.
        logger.warning(
            "sender: unexpected error for telegram_id=%s: %s",
            telegram_id, exc,
        )
        return False
