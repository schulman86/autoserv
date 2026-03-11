"""
bot/main.py
────────────
Точка входа Telegram-бота.

Запуск:
    python -m bot.main
    # или через Docker: CMD ["python", "-m", "bot.main"]

Бот работает в polling-режиме (MVP).
В production при необходимости переключается на webhook.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage

from bot.handlers.internal import run_internal_server
from bot.handlers.service import router as service_router
from bot.handlers.user import router as user_router
from common.config import settings

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    storage = RedisStorage.from_url(settings.redis_url)

    dp = Dispatcher(storage=storage)

    # Пользовательский FSM + команды (этап 3.1)
    dp.include_router(user_router)

    # Сервисный FSM + команды (этап 3.2)
    dp.include_router(service_router)

    logger.info("Starting bot polling + internal notify server...")
    try:
        await asyncio.gather(
            dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types()),
            run_internal_server(bot),
        )
    finally:
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
