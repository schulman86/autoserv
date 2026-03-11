"""
api/routers/service_profile.py
────────────────────────────────
Роутер для профиля автосервиса.

Эндпоинты:
    POST /      — upsert профиля (service only, idempotent)
    GET  /me    — получить свой профиль (service only)

Роутер тонкий: только HTTP-слой. Логика — в api/services/service_profile.py.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.dependencies.auth import ServiceOnly
from api.dependencies.db import DbSession
from api.schemas.service_profile import ServiceProfileResponse, ServiceProfileUpsert
from api.services.service_profile import get_my_profile, upsert_profile

router = APIRouter()


@router.post(
    "/",
    response_model=ServiceProfileResponse,
    status_code=200,
    summary="Создать или обновить профиль автосервиса",
    description=(
        "Idempotent. При первом вызове создаёт профиль, "
        "при повторных — обновляет все поля. "
        "is_active устанавливается в True при создании и не меняется при обновлении."
    ),
    responses={
        200: {"description": "Профиль создан или обновлён"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Только для role=service"},
        422: {"description": "Невалидные данные / недопустимые районы"},
    },
)
async def upsert(
    body: ServiceProfileUpsert,
    current_user: ServiceOnly,
    db: DbSession,
) -> ServiceProfileResponse:
    profile, _ = await upsert_profile(db, user_id=current_user.id, data=body)
    return ServiceProfileResponse.model_validate(profile)


@router.get(
    "/me",
    response_model=ServiceProfileResponse,
    summary="Получить свой профиль",
    responses={
        200: {"description": "Профиль автосервиса"},
        401: {"description": "Не аутентифицирован"},
        403: {"description": "Только для role=service"},
        404: {"description": "Профиль ещё не создан"},
    },
)
async def get_me(
    current_user: ServiceOnly,
    db: DbSession,
) -> ServiceProfileResponse:
    profile = await get_my_profile(db, user_id=current_user.id)
    return ServiceProfileResponse.model_validate(profile)
