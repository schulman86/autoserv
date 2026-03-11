"""
api/services/service_profile.py
────────────────────────────────
Бизнес-логика для профиля автосервиса.

Принцип: сервис не знает о HTTP/Request/Response.
Получает данные — возвращает результат или бросает AppError.

upsert_profile: idempotent — создаёт или обновляет профиль.
Стратегия: SELECT → найден → UPDATE, не найден → INSERT.
Используется Python-уровень вместо INSERT ON CONFLICT DO UPDATE
потому что SQLAlchemy 2.x async не поддерживает on_conflict_do_update
унифицированно между SQLite (тесты) и PostgreSQL (production).
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.exceptions import ForbiddenError, InvalidStatusError, NotFoundError
from api.schemas.service_profile import ServiceProfileUpsert
from common.config import settings
from common.models.service_profile import ServiceProfile

logger = logging.getLogger(__name__)


async def upsert_profile(
    db: AsyncSession,
    *,
    user_id: UUID,
    data: ServiceProfileUpsert,
) -> tuple[ServiceProfile, bool]:
    """
    Создать или обновить профиль автосервиса (idempotent).

    Стратегия: SELECT → найден → UPDATE полей, не найден → INSERT.

    Validates:
        - areas содержит только значения из settings.allowed_areas
        - areas не пустой (уже гарантировано схемой, повторяем для явности)

    Args:
        db:      AsyncSession
        user_id: UUID пользователя с role=SERVICE
        data:    Валидированные данные ServiceProfileUpsert

    Returns:
        Tuple[ServiceProfile, is_new: bool]
        is_new=True при создании, False при обновлении

    Raises:
        InvalidStatusError: если любой area не входит в allowed_areas (422)
    """
    _validate_areas(data.areas)

    result = await db.execute(
        select(ServiceProfile).where(ServiceProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()

    if profile is not None:
        # UPDATE: меняем все поля кроме user_id и is_active
        profile.name = data.name
        profile.description = data.description
        profile.areas = data.areas
        profile.services = data.services
        profile.phone = data.phone
        await db.flush()
        logger.info("service_profile: updated user_id=%s", user_id)
        return profile, False

    # INSERT
    profile = ServiceProfile(
        user_id=user_id,
        name=data.name,
        description=data.description,
        areas=data.areas,
        services=data.services,
        phone=data.phone,
        is_active=True,
    )
    db.add(profile)
    await db.flush()
    logger.info("service_profile: created user_id=%s id=%s", user_id, profile.id)
    return profile, True


async def get_my_profile(
    db: AsyncSession,
    *,
    user_id: UUID,
) -> ServiceProfile:
    """
    Получить профиль текущего сервиса.

    Args:
        db:      AsyncSession
        user_id: UUID пользователя с role=SERVICE

    Returns:
        ServiceProfile

    Raises:
        NotFoundError: если профиль не создан (404)
    """
    result = await db.execute(
        select(ServiceProfile).where(ServiceProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise NotFoundError(
            "Service profile not found. "
            "Please create your profile via POST /service-profile first."
        )
    return profile


def _validate_areas(areas: list[str]) -> None:
    """
    Проверяет, что все переданные районы входят в allowed_areas.

    Raises:
        InvalidStatusError: если хотя бы один район недопустим (422)
    """
    invalid = [a for a in areas if a not in settings.allowed_areas]
    if invalid:
        raise InvalidStatusError(
            f"Invalid areas: {', '.join(invalid)}. "
            f"Allowed areas: {', '.join(settings.allowed_areas)}"
        )
