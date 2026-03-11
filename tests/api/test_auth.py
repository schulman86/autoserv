"""
tests/api/test_auth.py
───────────────────────
Тесты POST /api/v1/auth/telegram.

DoD этапа 2.1:
  ✓ Idempotent auth — повторный запрос не создаёт дубль
  ✓ Повторный запрос → тот же user_id

Покрытие:
  - Happy path: создание user / service
  - Idempotency: повторный вызов → тот же id, is_new=False
  - Роль не меняется при повторном вызове с другой ролью
  - admin роль заблокирована на уровне схемы
  - Невалидные telegram_id отклоняются
  - Структура ответа соответствует контракту
  - Эндпоинт доступен без X-Telegram-ID (он открытый)
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.models.enums import RoleEnum
from common.models.user import User

ENDPOINT = "/api/v1/auth/telegram"


# ── Happy path ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_new_user(client: AsyncClient) -> None:
    """Первый вызов создаёт нового пользователя, is_new=True."""
    response = await client.post(ENDPOINT, json={"telegram_id": 100001, "role": "user"})

    assert response.status_code == 200
    body = response.json()
    assert body["is_new"] is True
    assert body["role"] == "user"
    assert "user_id" in body
    assert "created_at" in body
    # user_id — валидный UUID
    uuid.UUID(body["user_id"])


@pytest.mark.asyncio
async def test_create_new_service(client: AsyncClient) -> None:
    """Первый вызов с role=service создаёт сервисный аккаунт."""
    response = await client.post(ENDPOINT, json={"telegram_id": 100002, "role": "service"})

    assert response.status_code == 200
    body = response.json()
    assert body["is_new"] is True
    assert body["role"] == "service"


# ── Idempotency — DoD ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_idempotent_same_role(client: AsyncClient, db_session: AsyncSession) -> None:
    """
    DoD: повторный запрос → тот же user_id.
    Второй вызов с той же ролью не создаёт нового пользователя.
    """
    payload = {"telegram_id": 100010, "role": "user"}

    first = await client.post(ENDPOINT, json=payload)
    second = await client.post(ENDPOINT, json=payload)

    assert first.status_code == 200
    assert second.status_code == 200

    first_body = first.json()
    second_body = second.json()

    # Тот же user_id — главный критерий DoD
    assert first_body["user_id"] == second_body["user_id"]
    assert first_body["is_new"] is True
    assert second_body["is_new"] is False

    # В БД ровно одна запись
    count = await db_session.scalar(
        select(func.count()).where(User.telegram_id == 100010)
    )
    assert count == 1


@pytest.mark.asyncio
async def test_idempotent_different_role_ignored(client: AsyncClient) -> None:
    """
    Повторный вызов с другой ролью не меняет существующую роль.
    MVP: роль задаётся один раз при первом /start.
    """
    tg_id = 100020

    first = await client.post(ENDPOINT, json={"telegram_id": tg_id, "role": "user"})
    second = await client.post(ENDPOINT, json={"telegram_id": tg_id, "role": "service"})

    assert first.status_code == 200
    assert second.status_code == 200

    assert first.json()["user_id"] == second.json()["user_id"]
    # Роль осталась прежней — "user"
    assert second.json()["role"] == "user"
    assert second.json()["is_new"] is False


@pytest.mark.asyncio
async def test_multiple_calls_same_user_id(client: AsyncClient) -> None:
    """Три одинаковых запроса → один user_id во всех ответах."""
    payload = {"telegram_id": 100030, "role": "user"}
    responses = [await client.post(ENDPOINT, json=payload) for _ in range(3)]

    user_ids = {r.json()["user_id"] for r in responses}
    assert len(user_ids) == 1, f"Expected 1 unique user_id, got: {user_ids}"


# ── Validation ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_role_rejected(client: AsyncClient) -> None:
    """Самостоятельная регистрация с role=admin запрещена (422)."""
    response = await client.post(ENDPOINT, json={"telegram_id": 100040, "role": "admin"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_zero_telegram_id_rejected(client: AsyncClient) -> None:
    """telegram_id=0 — невалидный (422)."""
    response = await client.post(ENDPOINT, json={"telegram_id": 0, "role": "user"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_negative_telegram_id_rejected(client: AsyncClient) -> None:
    """Отрицательный telegram_id — невалидный (422)."""
    response = await client.post(ENDPOINT, json={"telegram_id": -1, "role": "user"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_missing_role_rejected(client: AsyncClient) -> None:
    """Отсутствие role — 422."""
    response = await client.post(ENDPOINT, json={"telegram_id": 100050})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_role_value_rejected(client: AsyncClient) -> None:
    """Неизвестное значение role — 422."""
    response = await client.post(ENDPOINT, json={"telegram_id": 100060, "role": "superadmin"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_missing_telegram_id_rejected(client: AsyncClient) -> None:
    """Отсутствие telegram_id — 422."""
    response = await client.post(ENDPOINT, json={"role": "user"})
    assert response.status_code == 422


# ── Response contract ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_response_schema_contract(client: AsyncClient) -> None:
    """Ответ соответствует задокументированной схеме AuthTelegramResponse."""
    response = await client.post(ENDPOINT, json={"telegram_id": 100070, "role": "user"})
    assert response.status_code == 200

    body = response.json()
    required_fields = {"user_id", "role", "is_new", "created_at"}
    assert required_fields.issubset(body.keys()), (
        f"Missing fields: {required_fields - body.keys()}"
    )
    # Типы
    assert isinstance(body["user_id"], str)
    assert isinstance(body["role"], str)
    assert isinstance(body["is_new"], bool)
    assert isinstance(body["created_at"], str)


@pytest.mark.asyncio
async def test_no_auth_header_required(client: AsyncClient) -> None:
    """
    POST /auth/telegram не требует X-Telegram-ID заголовка.
    Это единственный открытый эндпоинт — точка входа для бота.
    """
    # Явно НЕ передаём X-Telegram-ID
    response = await client.post(
        ENDPOINT,
        json={"telegram_id": 100080, "role": "user"},
        headers={},  # без заголовков
    )
    # Должен вернуть 200, а не 401
    assert response.status_code == 200


# ── DB state verification ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_user_persisted_in_db(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """После создания пользователь реально существует в БД."""
    tg_id = 100090
    response = await client.post(ENDPOINT, json={"telegram_id": tg_id, "role": "service"})
    assert response.status_code == 200
    user_id = response.json()["user_id"]

    # Ищем в БД напрямую
    result = await db_session.execute(
        select(User).where(User.telegram_id == tg_id)
    )
    user = result.scalar_one_or_none()

    assert user is not None
    assert str(user.id) == user_id
    assert user.telegram_id == tg_id
    assert user.role == RoleEnum.SERVICE
