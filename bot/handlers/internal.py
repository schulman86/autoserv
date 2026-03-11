"""
bot/handlers/internal.py
─────────────────────────
Внутренний HTTP endpoint бота для приёма уведомлений от API.

Архитектура:
    API → POST /internal/notify → бот → Bot.send_message(telegram_id, text)

Запускается как отдельный aiohttp веб-сервер рядом с aiogram polling.
Порт: 8001 (настраивается через BOT_INTERNAL_PORT в .env).

Аутентификация: заголовок X-Internal-Secret = settings.api_internal_secret.
При несовпадении — 403 Forbidden.

Использование в bot/main.py:
    from bot.handlers.internal import create_internal_app, run_internal_server
    asyncio.gather(dp.start_polling(bot), run_internal_server(bot))
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web
from aiogram import Bot

from common.config import settings

logger = logging.getLogger(__name__)

# Порт внутреннего HTTP сервера (не конфликтует с основным API на 8000)
BOT_INTERNAL_PORT = 8001


async def _notify_handler(request: web.Request) -> web.Response:
    """
    POST /internal/notify
    Body: {"telegram_id": int, "text": str}
    Header: X-Internal-Secret: <secret>
    """
    # Проверяем внутренний секрет
    secret = request.headers.get("X-Internal-Secret", "")
    if secret != settings.api_internal_secret:
        logger.warning(
            "internal: unauthorized notify attempt from %s",
            request.remote,
        )
        return web.json_response({"error": "Forbidden"}, status=403)

    try:
        data: dict[str, Any] = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    telegram_id = data.get("telegram_id")
    text = data.get("text", "")

    if not isinstance(telegram_id, int) or not text:
        return web.json_response(
            {"error": "telegram_id (int) and text (str) are required"},
            status=400,
        )

    bot: Bot = request.app["bot"]

    try:
        await bot.send_message(chat_id=telegram_id, text=text)
        logger.debug("internal: sent message to telegram_id=%s", telegram_id)
        return web.json_response({"ok": True})
    except Exception as exc:
        logger.warning(
            "internal: failed to send to telegram_id=%s: %s",
            telegram_id, exc,
        )
        # Возвращаем 200 чтобы API не логировал как ошибку повторно.
        # API уже получил 200 → всё нормально, детали в логах бота.
        return web.json_response({"ok": False, "error": str(exc)})


def create_internal_app(bot: Bot) -> web.Application:
    """
    Создать aiohttp-приложение с внутренним endpoint'ом.

    Args:
        bot: Инициализированный экземпляр aiogram.Bot

    Returns:
        web.Application готовое к запуску
    """
    app = web.Application()
    app["bot"] = bot
    app.router.add_post("/internal/notify", _notify_handler)
    return app


async def run_internal_server(bot: Bot, port: int = BOT_INTERNAL_PORT) -> None:
    """
    Запустить внутренний HTTP сервер.
    Предназначен для запуска через asyncio.gather вместе с polling.

    Args:
        bot:  Инициализированный aiogram.Bot
        port: Порт для прослушивания (по умолчанию BOT_INTERNAL_PORT=8001)
    """
    app = create_internal_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info("Internal notify server started on port %d", port)

    # Держим сервер запущенным бесконечно (до отмены задачи)
    import asyncio
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
