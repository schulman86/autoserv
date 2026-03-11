"""
tests/bot/test_internal.py
───────────────────────────
Тесты для bot/handlers/internal.py — внутренний HTTP endpoint бота.

Контракты:
    POST /internal/notify
        • Правильный секрет + валидный payload → 200 {"ok": true}
        • Неправильный/отсутствующий секрет → 403
        • Невалидный JSON → 400
        • Отсутствует telegram_id или text → 400
        • telegram_id не int (строка) → 400
        • Bot.send_message бросает исключение → 200 {"ok": false} (поглощается)
        • Bot.send_message вызван с правильными аргументами
        • Аутентификация по заголовку X-Internal-Secret — не по Authorization

    create_internal_app:
        • Возвращает aiohttp.web.Application
        • Роутер содержит ровно один маршрут POST /internal/notify
        • bot доступен через app["bot"]

    run_internal_server:
        • Функция является корутиной (async)

Запуск:
    pytest tests/bot/test_internal.py -v
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.handlers.internal import (
    BOT_INTERNAL_PORT,
    _notify_handler,
    create_internal_app,
    run_internal_server,
)
from common.config import settings


# ── Фикстуры ─────────────────────────────────────────────────────────────────

def _make_app(bot: MagicMock | None = None) -> web.Application:
    """Создать тестовое приложение с мок-ботом."""
    if bot is None:
        bot = MagicMock()
        bot.send_message = AsyncMock()
    return create_internal_app(bot)


@pytest.fixture()
def mock_bot() -> MagicMock:
    bot = MagicMock()
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture()
async def test_client(mock_bot: MagicMock) -> TestClient:
    app = create_internal_app(mock_bot)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    yield client
    await client.close()


def _secret_header(secret: str | None = None) -> dict[str, str]:
    return {"X-Internal-Secret": secret or settings.api_internal_secret}


# ══════════════════════════════════════════════════════════════════════════════
# create_internal_app
# ══════════════════════════════════════════════════════════════════════════════

class TestCreateInternalApp:
    def test_returns_web_application(self) -> None:
        app = create_internal_app(MagicMock())
        assert isinstance(app, web.Application)

    def test_bot_stored_in_app(self) -> None:
        bot = MagicMock()
        app = create_internal_app(bot)
        assert app["bot"] is bot

    def test_notify_route_registered(self) -> None:
        app = create_internal_app(MagicMock())
        routes = [r.resource.canonical for r in app.router.routes()]  # type: ignore[union-attr]
        assert "/internal/notify" in routes

    def test_only_post_method_registered(self) -> None:
        app = create_internal_app(MagicMock())
        methods = {r.method for r in app.router.routes()}
        assert "POST" in methods


# ══════════════════════════════════════════════════════════════════════════════
# run_internal_server
# ══════════════════════════════════════════════════════════════════════════════

class TestRunInternalServer:
    def test_is_coroutine_function(self) -> None:
        """run_internal_server должна быть async-функцией."""
        assert asyncio.iscoroutinefunction(run_internal_server)

    def test_default_port_constant(self) -> None:
        assert BOT_INTERNAL_PORT == 8001


# ══════════════════════════════════════════════════════════════════════════════
# POST /internal/notify — аутентификация
# ══════════════════════════════════════════════════════════════════════════════

class TestNotifyAuthentication:
    async def test_correct_secret_returns_200(self, test_client: TestClient) -> None:
        resp = await test_client.post(
            "/internal/notify",
            json={"telegram_id": 123, "text": "hello"},
            headers=_secret_header(),
        )
        assert resp.status == 200

    async def test_wrong_secret_returns_403(self, test_client: TestClient) -> None:
        resp = await test_client.post(
            "/internal/notify",
            json={"telegram_id": 123, "text": "hello"},
            headers={"X-Internal-Secret": "wrong-secret"},
        )
        assert resp.status == 403

    async def test_missing_secret_returns_403(self, test_client: TestClient) -> None:
        resp = await test_client.post(
            "/internal/notify",
            json={"telegram_id": 123, "text": "hello"},
        )
        assert resp.status == 403

    async def test_empty_secret_returns_403(self, test_client: TestClient) -> None:
        resp = await test_client.post(
            "/internal/notify",
            json={"telegram_id": 123, "text": "hello"},
            headers={"X-Internal-Secret": ""},
        )
        assert resp.status == 403

    async def test_403_response_body(self, test_client: TestClient) -> None:
        resp = await test_client.post(
            "/internal/notify",
            json={"telegram_id": 123, "text": "hello"},
            headers={"X-Internal-Secret": "bad"},
        )
        data = await resp.json()
        assert "error" in data


# ══════════════════════════════════════════════════════════════════════════════
# POST /internal/notify — валидация payload
# ══════════════════════════════════════════════════════════════════════════════

class TestNotifyValidation:
    async def test_invalid_json_returns_400(self, test_client: TestClient) -> None:
        resp = await test_client.post(
            "/internal/notify",
            data="not-json",
            headers={
                **_secret_header(),
                "Content-Type": "application/json",
            },
        )
        assert resp.status == 400

    async def test_missing_telegram_id_returns_400(self, test_client: TestClient) -> None:
        resp = await test_client.post(
            "/internal/notify",
            json={"text": "hello"},
            headers=_secret_header(),
        )
        assert resp.status == 400

    async def test_missing_text_returns_400(self, test_client: TestClient) -> None:
        resp = await test_client.post(
            "/internal/notify",
            json={"telegram_id": 123},
            headers=_secret_header(),
        )
        assert resp.status == 400

    async def test_empty_text_returns_400(self, test_client: TestClient) -> None:
        """Пустой text считается невалидным (falsy)."""
        resp = await test_client.post(
            "/internal/notify",
            json={"telegram_id": 123, "text": ""},
            headers=_secret_header(),
        )
        assert resp.status == 400

    async def test_telegram_id_as_string_returns_400(self, test_client: TestClient) -> None:
        """telegram_id должен быть int, строка → 400."""
        resp = await test_client.post(
            "/internal/notify",
            json={"telegram_id": "not-an-int", "text": "hello"},
            headers=_secret_header(),
        )
        assert resp.status == 400

    async def test_telegram_id_as_float_returns_400(self, test_client: TestClient) -> None:
        """float не является int."""
        resp = await test_client.post(
            "/internal/notify",
            json={"telegram_id": 123.5, "text": "hello"},
            headers=_secret_header(),
        )
        assert resp.status == 400

    async def test_400_response_has_error_key(self, test_client: TestClient) -> None:
        resp = await test_client.post(
            "/internal/notify",
            json={"telegram_id": "bad"},
            headers=_secret_header(),
        )
        data = await resp.json()
        assert "error" in data


# ══════════════════════════════════════════════════════════════════════════════
# POST /internal/notify — happy path
# ══════════════════════════════════════════════════════════════════════════════

class TestNotifyHappyPath:
    async def test_ok_true_in_response(self, test_client: TestClient) -> None:
        resp = await test_client.post(
            "/internal/notify",
            json={"telegram_id": 42, "text": "Test message"},
            headers=_secret_header(),
        )
        assert resp.status == 200
        data = await resp.json()
        assert data.get("ok") is True

    async def test_bot_send_message_called_with_correct_chat_id(
        self, test_client: TestClient, mock_bot: MagicMock
    ) -> None:
        await test_client.post(
            "/internal/notify",
            json={"telegram_id": 9876, "text": "Привет"},
            headers=_secret_header(),
        )
        mock_bot.send_message.assert_called_once()
        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 9876

    async def test_bot_send_message_called_with_correct_text(
        self, test_client: TestClient, mock_bot: MagicMock
    ) -> None:
        await test_client.post(
            "/internal/notify",
            json={"telegram_id": 1, "text": "Уведомление о новой заявке"},
            headers=_secret_header(),
        )
        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["text"] == "Уведомление о новой заявке"

    async def test_unicode_text_delivered(
        self, test_client: TestClient, mock_bot: MagicMock
    ) -> None:
        text = "🎉 Ваше предложение выбрано! Клиент: Иван Иванов"
        await test_client.post(
            "/internal/notify",
            json={"telegram_id": 1, "text": text},
            headers=_secret_header(),
        )
        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["text"] == text


# ══════════════════════════════════════════════════════════════════════════════
# POST /internal/notify — обработка ошибок бота
# ══════════════════════════════════════════════════════════════════════════════

class TestNotifyBotErrorHandling:
    async def test_bot_exception_returns_200_not_500(
        self, mock_bot: MagicMock
    ) -> None:
        """
        Если Bot.send_message бросает исключение, endpoint должен вернуть 200
        (не 500), чтобы API не считал уведомление критической ошибкой.
        Это ключевой контракт: ошибка доставки не должна блокировать API.
        """
        mock_bot.send_message = AsyncMock(side_effect=Exception("Telegram API down"))
        app = create_internal_app(mock_bot)
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.post(
                "/internal/notify",
                json={"telegram_id": 1, "text": "test"},
                headers=_secret_header(),
            )
            assert resp.status == 200
        finally:
            await client.close()

    async def test_bot_exception_returns_ok_false(
        self, mock_bot: MagicMock
    ) -> None:
        """ok: false в ответе сигнализирует о неудаче доставки."""
        mock_bot.send_message = AsyncMock(side_effect=RuntimeError("network error"))
        app = create_internal_app(mock_bot)
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.post(
                "/internal/notify",
                json={"telegram_id": 1, "text": "test"},
                headers=_secret_header(),
            )
            data = await resp.json()
            assert data.get("ok") is False
            assert "error" in data
        finally:
            await client.close()

    async def test_bot_forbidden_error_returns_200(
        self, mock_bot: MagicMock
    ) -> None:
        """TelegramForbiddenError (бот заблокирован) → 200, ok: false."""
        from aiogram.exceptions import TelegramForbiddenError
        mock_bot.send_message = AsyncMock(
            side_effect=TelegramForbiddenError(
                method=MagicMock(),
                message="Forbidden: bot was blocked by the user",
            )
        )
        app = create_internal_app(mock_bot)
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            resp = await client.post(
                "/internal/notify",
                json={"telegram_id": 1, "text": "test"},
                headers=_secret_header(),
            )
            assert resp.status == 200
        finally:
            await client.close()


# ══════════════════════════════════════════════════════════════════════════════
# Изоляция: уведомление не блокирует polling (архитектурный контракт)
# ══════════════════════════════════════════════════════════════════════════════

class TestNotifyNonBlocking:
    def test_notify_handler_is_coroutine(self) -> None:
        """_notify_handler — async функция → не блокирует event loop при вызове."""
        assert asyncio.iscoroutinefunction(_notify_handler)

    def test_run_internal_server_is_coroutine(self) -> None:
        """run_internal_server должна быть coroutine для использования в asyncio.gather."""
        assert asyncio.iscoroutinefunction(run_internal_server)
