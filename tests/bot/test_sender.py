"""
tests/bot/test_sender.py
─────────────────────────
Тесты для bot/utils/sender.py — утилита отправки Telegram-сообщений.

Контракты, которые проверяем:
    1. Happy path: bot.send_message вызван с правильными аргументами → True.
    2. TelegramForbiddenError (пользователь заблокировал бота) → False, не бросает.
    3. TelegramBadRequest (некорректный запрос) → False, не бросает.
    4. Любое непредвиденное исключение → False, не бросает.
    5. parse_mode=None по умолчанию — передаётся в bot.send_message.
    6. parse_mode="HTML" передаётся корректно.
    7. Возвращаемое значение является bool, не None.

Запуск:
    pytest tests/bot/test_sender.py -v
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from bot.utils.sender import send_message


def _make_bot(side_effect: Exception | None = None) -> MagicMock:
    """Создать мок Bot с настраиваемым поведением send_message."""
    bot = MagicMock()
    if side_effect is not None:
        bot.send_message = AsyncMock(side_effect=side_effect)
    else:
        bot.send_message = AsyncMock(return_value=MagicMock())
    return bot


class TestSendMessageSuccess:
    async def test_returns_true_on_success(self) -> None:
        bot = _make_bot()
        result = await send_message(bot, telegram_id=123, text="Hello")
        assert result is True

    async def test_calls_send_message_with_correct_chat_id(self) -> None:
        bot = _make_bot()
        await send_message(bot, telegram_id=456, text="Test")
        bot.send_message.assert_called_once()
        call_kwargs = bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 456

    async def test_calls_send_message_with_correct_text(self) -> None:
        bot = _make_bot()
        await send_message(bot, telegram_id=1, text="Привет мир")
        call_kwargs = bot.send_message.call_args.kwargs
        assert call_kwargs["text"] == "Привет мир"

    async def test_default_parse_mode_is_none(self) -> None:
        bot = _make_bot()
        await send_message(bot, telegram_id=1, text="test")
        call_kwargs = bot.send_message.call_args.kwargs
        assert call_kwargs["parse_mode"] is None

    async def test_custom_parse_mode_passed_through(self) -> None:
        bot = _make_bot()
        await send_message(bot, telegram_id=1, text="<b>bold</b>", parse_mode="HTML")
        call_kwargs = bot.send_message.call_args.kwargs
        assert call_kwargs["parse_mode"] == "HTML"

    async def test_return_value_is_bool(self) -> None:
        bot = _make_bot()
        result = await send_message(bot, telegram_id=1, text="x")
        assert isinstance(result, bool)


class TestSendMessageForbidden:
    async def test_returns_false_on_forbidden(self) -> None:
        exc = TelegramForbiddenError(method=MagicMock(), message="Forbidden: bot was blocked by the user")
        bot = _make_bot(side_effect=exc)
        result = await send_message(bot, telegram_id=999, text="msg")
        assert result is False

    async def test_does_not_raise_on_forbidden(self) -> None:
        exc = TelegramForbiddenError(method=MagicMock(), message="Forbidden: bot was blocked by the user")
        bot = _make_bot(side_effect=exc)
        # Не должно бросить исключение
        await send_message(bot, telegram_id=999, text="msg")


class TestSendMessageBadRequest:
    async def test_returns_false_on_bad_request(self) -> None:
        exc = TelegramBadRequest(method=MagicMock(), message="Bad Request: chat not found")
        bot = _make_bot(side_effect=exc)
        result = await send_message(bot, telegram_id=888, text="msg")
        assert result is False

    async def test_does_not_raise_on_bad_request(self) -> None:
        exc = TelegramBadRequest(method=MagicMock(), message="Bad Request: chat not found")
        bot = _make_bot(side_effect=exc)
        await send_message(bot, telegram_id=888, text="msg")


class TestSendMessageUnexpectedError:
    async def test_returns_false_on_network_error(self) -> None:
        bot = _make_bot(side_effect=ConnectionError("Network unreachable"))
        result = await send_message(bot, telegram_id=777, text="msg")
        assert result is False

    async def test_does_not_raise_on_network_error(self) -> None:
        bot = _make_bot(side_effect=OSError("Timeout"))
        await send_message(bot, telegram_id=777, text="msg")

    async def test_returns_false_on_runtime_error(self) -> None:
        bot = _make_bot(side_effect=RuntimeError("Unexpected"))
        result = await send_message(bot, telegram_id=111, text="msg")
        assert result is False

    async def test_does_not_raise_on_any_exception(self) -> None:
        bot = _make_bot(side_effect=Exception("Anything"))
        # Функция НИКОГДА не должна пробрасывать исключения
        result = await send_message(bot, telegram_id=111, text="msg")
        assert result is False


class TestSendMessageEdgeCases:
    async def test_empty_text_still_calls_bot(self) -> None:
        """Пустой текст — отправляем как есть, не фильтруем здесь."""
        bot = _make_bot()
        result = await send_message(bot, telegram_id=1, text="")
        assert result is True
        bot.send_message.assert_called_once()

    async def test_long_text_passes_through(self) -> None:
        """Длинный текст не обрезается в sender (это забота вызывающего кода)."""
        bot = _make_bot()
        long_text = "А" * 4096
        result = await send_message(bot, telegram_id=1, text=long_text)
        assert result is True
        call_kwargs = bot.send_message.call_args.kwargs
        assert call_kwargs["text"] == long_text

    async def test_large_telegram_id(self) -> None:
        """telegram_id может быть большим числом (channel/group IDs)."""
        bot = _make_bot()
        result = await send_message(bot, telegram_id=9_999_999_999, text="test")
        assert result is True
        call_kwargs = bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 9_999_999_999
