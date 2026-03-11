"""
api/services/auth.py
─────────────────────
Бизнес-логика аутентификации / регистрации пользователей.

Принцип: сервис не знает о HTTP, Request, Response.
Получает данные — возвращает результат или бросает AppError.

Idempotency-стратегия:
    SELECT → найден   → вернуть существующего (is_new=False)
    SELECT → не найден → INSERT → вернуть нового (is_new=True)

    Race condition (два одновременных /start):
        Первый INSERT побеждает, второй получает UniqueViolation.
        Обрабатываем: повторный SELECT после IntegrityError.
        Итог: оба запроса возвращают одного и того же пользователя.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.exceptions import ConflictError
from common.models.enums import RoleEnum
from common.models.user import User

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuthResult:
    """Результат вызова get_or_create_user."""
    user: User
    is_new: bool


async def get_or_create_user(
    db: AsyncSession,
    *,
    telegram_id: int,
    role: RoleEnum,
) -> AuthResult:
    """
    Найти пользователя по telegram_id или создать нового.

    Idempotent: повторный вызов с теми же аргументами
    возвращает того же пользователя (is_new=False).

    Если пользователь уже существует с другой ролью —
    возвращает существующего без изменений (роль не меняется на MVP).

    Args:
        db:          AsyncSession (не коммитит — коммит на стороне вызывающего)
        telegram_id: Telegram user ID
        role:        Запрошенная роль (игнорируется если пользователь уже есть)

    Returns:
        AuthResult(user, is_new)

    Raises:
        ConflictError: если IntegrityError не удалось разрешить
                       (не должно случаться при нормальной работе)
    """
    # ── Fast path: пользователь уже существует ────────────────────────────────
    existing = await _find_by_telegram_id(db, telegram_id)
    if existing is not None:
        logger.debug("auth: existing user tg=%d role=%s", telegram_id, existing.role.value)
        return AuthResult(user=existing, is_new=False)

    # ── Slow path: создать нового ─────────────────────────────────────────────
    user = User(telegram_id=telegram_id, role=role)
    db.add(user)

    try:
        await db.flush()  # Получаем id, не коммитим — коммит делает get_db dependency
        logger.info("auth: created user tg=%d role=%s id=%s", telegram_id, role.value, user.id)
        return AuthResult(user=user, is_new=True)

    except IntegrityError:
        # Race condition: параллельный запрос успел вставить раньше нас
        await db.rollback()
        logger.warning(
            "auth: race condition on tg=%d, falling back to SELECT", telegram_id
        )
        resolved = await _find_by_telegram_id(db, telegram_id)
        if resolved is None:
            # Совсем не ожидаемая ситуация
            raise ConflictError(
                f"Failed to create or find user with telegram_id={telegram_id}"
            )
        return AuthResult(user=resolved, is_new=False)


async def _find_by_telegram_id(db: AsyncSession, telegram_id: int) -> User | None:
    """Поиск пользователя по telegram_id. Использует уникальный индекс."""
    result = await db.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()
