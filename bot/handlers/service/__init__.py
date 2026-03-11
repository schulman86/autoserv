"""
bot/handlers/service/__init__.py
──────────────────────────────────
Агрегирующий роутер для всех хендлеров автосервиса.

Порядок включения важен:
  1. profile  — содержит /cancel (перехватывает раньше start)
  2. offers   — OfferFSM и история предложений
  3. requests — просмотр доступных заявок
  4. start    — /start, /help, главное меню (последним, чтобы не перекрывать FSM)
"""

from aiogram import Router

from bot.handlers.service import offers, profile, requests, start

router = Router(name="service")

router.include_router(profile.router)
router.include_router(offers.router)
router.include_router(requests.router)
router.include_router(start.router)

__all__ = ["router"]
