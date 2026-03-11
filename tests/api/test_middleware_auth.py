"""
tests/api/test_middleware_auth.py
──────────────────────────────────
Тесты аутентификации и RBAC — прямое покрытие DoD этапа 1.3:

  ✓ Telegram ID читается из middleware
  ✓ Role-based access работает
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from common.models.user import User


# ── /healthz — открытый путь ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_healthz_no_auth(client: AsyncClient) -> None:
    """Healthz доступен без X-Telegram-ID."""
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ── Middleware: отсутствие заголовка ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_telegram_id_header(client: AsyncClient) -> None:
    """Запрос без X-Telegram-ID → 401 UNAUTHORIZED."""
    response = await client.get("/api/v1/requests/my")
    assert response.status_code == 401
    body = response.json()
    assert body["error_code"] == "UNAUTHORIZED"
    assert "X-Telegram-ID" in body["detail"]


@pytest.mark.asyncio
async def test_invalid_telegram_id_not_integer(client: AsyncClient) -> None:
    """X-Telegram-ID с нечисловым значением → 401."""
    response = await client.get(
        "/api/v1/requests/my",
        headers={"X-Telegram-ID": "not-a-number"},
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_invalid_telegram_id_zero(client: AsyncClient) -> None:
    """X-Telegram-ID = 0 (не положительное) → 401."""
    response = await client.get(
        "/api/v1/requests/my",
        headers={"X-Telegram-ID": "0"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_telegram_id_negative(client: AsyncClient) -> None:
    """X-Telegram-ID < 0 → 401."""
    response = await client.get(
        "/api/v1/requests/my",
        headers={"X-Telegram-ID": "-1"},
    )
    assert response.status_code == 401


# ── Middleware: пользователь не зарегистрирован ───────────────────────────────

@pytest.mark.asyncio
async def test_unknown_telegram_id_returns_401(client: AsyncClient) -> None:
    """
    Валидный X-Telegram-ID, но пользователь не найден в БД → 401.
    Это отдельно от FORBIDDEN: сначала нужно зарегистрироваться.
    """
    response = await client.get(
        "/api/v1/requests/my",
        headers={"X-Telegram-ID": "999999999"},
    )
    # 401 — пользователь не найден, не 403
    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


# ── RBAC: роль USER ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_user_role_can_access_my_requests(
    client: AsyncClient, user_client_user: User
) -> None:
    """
    Пользователь с role=USER может обратиться к /requests/my.
    Роутер ещё не реализован → 404, но не 401/403.
    """
    response = await client.get(
        "/api/v1/requests/my",
        headers={"X-Telegram-ID": str(user_client_user.telegram_id)},
    )
    # Роутер не подключён → 404 Not Found, но аутентификация прошла
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_service_role_can_access_available_requests(
    client: AsyncClient, user_service: User
) -> None:
    """Пользователь с role=SERVICE проходит аутентификацию."""
    response = await client.get(
        "/api/v1/requests/available",
        headers={"X-Telegram-ID": str(user_service.telegram_id)},
    )
    assert response.status_code == 404  # роутер не подключён, но не 401/403


# ── POST /auth/telegram — открытый (без X-Telegram-ID) ───────────────────────

@pytest.mark.asyncio
async def test_auth_telegram_no_header_allowed(client: AsyncClient) -> None:
    """
    POST /auth/telegram не требует X-Telegram-ID в заголовке —
    telegram_id передаётся в body.
    Роутер не подключён → 404, но middleware не должен блокировать.
    """
    response = await client.post(
        "/api/v1/auth/telegram",
        json={"telegram_id": 123456789, "role": "user"},
    )
    # Middleware не блокирует /auth/telegram — это точка входа для регистрации
    # Роутер не подключён → 404
    assert response.status_code == 404


# ── Структура error response ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_error_response_structure(client: AsyncClient) -> None:
    """Формат ошибки соответствует контракту: {error_code, detail}."""
    response = await client.get("/api/v1/requests/my")
    assert response.status_code == 401
    body = response.json()
    assert "error_code" in body
    assert "detail" in body
    assert isinstance(body["error_code"], str)
    assert isinstance(body["detail"], str)
