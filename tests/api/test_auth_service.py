"""
tests/api/test_auth_service.py
───────────────────────────────
Unit-тесты сервисного слоя api/services/auth.py.

Тестируем логику напрямую, без HTTP — быстро и точно.
Особое внимание: race condition handling через IntegrityError.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from unittest.mock import AsyncMock, MagicMock, patch

from api.services.auth import AuthResult, get_or_create_user
from common.models.enums import RoleEnum
from common.models.user import User


# ── Базовый функционал ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_creates_new_user(db_session: AsyncSession) -> None:
    """Новый пользователь создаётся, is_new=True."""
    result = await get_or_create_user(
        db_session, telegram_id=500001, role=RoleEnum.USER
    )

    assert isinstance(result, AuthResult)
    assert result.is_new is True
    assert result.user.telegram_id == 500001
    assert result.user.role == RoleEnum.USER
    assert result.user.id is not None


@pytest.mark.asyncio
async def test_returns_existing_user(db_session: AsyncSession) -> None:
    """Второй вызов для того же telegram_id — тот же объект, is_new=False."""
    first = await get_or_create_user(db_session, telegram_id=500002, role=RoleEnum.USER)
    second = await get_or_create_user(db_session, telegram_id=500002, role=RoleEnum.USER)

    assert first.user.id == second.user.id
    assert first.is_new is True
    assert second.is_new is False


@pytest.mark.asyncio
async def test_role_not_changed_on_repeat(db_session: AsyncSession) -> None:
    """При повторном вызове с другой ролью — роль оригинала сохраняется."""
    original = await get_or_create_user(
        db_session, telegram_id=500003, role=RoleEnum.USER
    )
    repeat = await get_or_create_user(
        db_session, telegram_id=500003, role=RoleEnum.SERVICE
    )

    assert original.user.id == repeat.user.id
    assert repeat.user.role == RoleEnum.USER  # не SERVICE


@pytest.mark.asyncio
async def test_different_telegram_ids_independent(db_session: AsyncSession) -> None:
    """Разные telegram_id создают разных пользователей."""
    user_a = await get_or_create_user(db_session, telegram_id=500010, role=RoleEnum.USER)
    user_b = await get_or_create_user(db_session, telegram_id=500011, role=RoleEnum.SERVICE)

    assert user_a.user.id != user_b.user.id
    assert user_a.is_new is True
    assert user_b.is_new is True


# ── Race condition ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_race_condition_integrity_error_resolved(db_session: AsyncSession) -> None:
    """
    Симулируем race condition: первый flush бросает IntegrityError,
    после чего сервис должен найти пользователя повторным SELECT.

    Это покрывает кейс: два параллельных /start от одного пользователя.
    """
    tg_id = 500020
    # Создаём пользователя заранее (симулируем "параллельный" INSERT)
    existing = await get_or_create_user(db_session, telegram_id=tg_id, role=RoleEnum.USER)
    assert existing.is_new is True

    # Теперь симулируем IntegrityError при второй попытке insert
    # Патчим db.flush() так, чтобы он один раз бросил IntegrityError
    original_flush = db_session.flush

    call_count = 0

    async def mock_flush(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Первый flush — бросаем IntegrityError (имитируем гонку)
            raise IntegrityError(
                statement="INSERT INTO users",
                params={},
                orig=Exception("UNIQUE constraint failed"),
            )
        return await original_flush(*args, **kwargs)

    with patch.object(db_session, "flush", side_effect=mock_flush):
        # rollback + повторный SELECT должны вернуть существующего
        result = await get_or_create_user(
            db_session, telegram_id=tg_id, role=RoleEnum.USER
        )

    assert result.user.id == existing.user.id
    assert result.is_new is False


# ── AuthResult dataclass ──────────────────────────────────────────────────────

def test_auth_result_immutable() -> None:
    """AuthResult — frozen dataclass, нельзя изменить после создания."""
    user = MagicMock(spec=User)
    result = AuthResult(user=user, is_new=True)

    with pytest.raises((AttributeError, TypeError)):
        result.is_new = False  # type: ignore[misc]
