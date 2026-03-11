"""
api/routers/auth.py
────────────────────
Роутер аутентификации.

Единственный эндпоинт: POST /auth/telegram
Открытый (не требует X-Telegram-ID заголовка) — см. OPEN_PATHS в middleware.

Роутер тонкий: только HTTP-слой.
Вся логика — в api/services/auth.py.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.dependencies.db import DbSession
from api.schemas.auth import AuthTelegramRequest, AuthTelegramResponse
from api.services.auth import get_or_create_user

router = APIRouter()


@router.post(
    "/telegram",
    response_model=AuthTelegramResponse,
    status_code=200,
    summary="Авторизация по Telegram ID",
    description=(
        "Idempotent. Создаёт нового пользователя или возвращает существующего. "
        "Вызывается ботом при каждом `/start`. "
        "Роль устанавливается только при первом вызове и далее не меняется."
    ),
    responses={
        200: {"description": "Пользователь найден или создан"},
        400: {"description": "Некорректные данные запроса"},
        409: {"description": "Конфликт при создании (race condition)"},
    },
)
async def auth_telegram(
    body: AuthTelegramRequest,
    db: DbSession,
) -> AuthTelegramResponse:
    result = await get_or_create_user(
        db,
        telegram_id=body.telegram_id,
        role=body.role,
    )
    return AuthTelegramResponse(
        user_id=result.user.id,
        role=result.user.role,
        is_new=result.is_new,
        created_at=result.user.created_at,
    )
