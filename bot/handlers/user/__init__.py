"""
bot/handlers/user/__init__.py
──────────────────────────────
Агрегирующий роутер для всех пользовательских хендлеров.

Порядок включения важен:
  1. create_request — содержит общий /cancel хендлер (должен быть раньше my_requests)
  2. my_requests
  3. offers
  4. start — /start, /help, главное меню (в конце, чтобы не перекрывать FSM)
"""

from aiogram import Router

from bot.handlers.user import create_request, my_requests, offers, start

router = Router(name="user")

router.include_router(create_request.router)
router.include_router(my_requests.router)
router.include_router(offers.router)
router.include_router(start.router)

__all__ = ["router"]
