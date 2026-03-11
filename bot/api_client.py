"""
bot/api_client.py
──────────────────
Тонкий HTTP-клиент для вызовов бота к внутреннему API.

Принцип: бот не обращается к БД напрямую — только через API.
Вся бизнес-логика живёт в api/, бот отвечает только за UX/FSM.

Использование:
    async with ApiClient(telegram_id=message.from_user.id) as client:
        user = await client.auth_telegram(telegram_id=123, role="user")

Аутентификация:
    - Authorization: Bearer <api_internal_secret>  — подтверждает что клиент доверенный
    - X-Telegram-ID: <telegram_id>                 — идентифицирует пользователя в API
      Передаётся при создании ApiClient(telegram_id=...).
      Для эндпоинтов без аутентификации (например /auth/telegram) можно не передавать.
"""

from __future__ import annotations

from typing import Any

import httpx

from common.config import settings


class ApiClient:
    """
    Async HTTP-клиент для внутренних запросов бот → API.
    Использовать как async context manager.

    Args:
        telegram_id: Telegram ID текущего пользователя.
                     Передаётся как X-Telegram-ID заголовок в каждый запрос.
                     Обязателен для всех защищённых эндпоинтов.
        base_url:    Переопределение базового URL (для тестов).
    """

    def __init__(
        self,
        telegram_id: int | None = None,
        base_url: str | None = None,
    ) -> None:
        self._base_url = base_url or settings.api_base_url
        self._headers: dict[str, str] = {
            "Authorization": f"Bearer {settings.api_internal_secret}",
            "Content-Type": "application/json",
        }
        if telegram_id is not None:
            self._headers["X-Telegram-ID"] = str(telegram_id)
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "ApiClient":
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=10.0,
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("ApiClient must be used as async context manager")
        return self._client

    async def _post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.client.post(path, **kwargs)
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    async def _get(self, path: str, **kwargs: Any) -> dict[str, Any] | list[Any]:
        response = await self.client.get(path, **kwargs)
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    async def _patch(self, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self.client.patch(path, **kwargs)
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    # ── Auth ─────────────────────────────────────────────────────────────────

    async def auth_telegram(self, telegram_id: int, role: str) -> dict[str, Any]:
        """POST /auth/telegram — idempotent get_or_create."""
        return await self._post(
            "/api/v1/auth/telegram",
            json={"telegram_id": telegram_id, "role": role},
        )

    # ── Requests ─────────────────────────────────────────────────────────────

    async def create_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/api/v1/requests", json=payload)

    async def get_my_requests(self, telegram_id: int) -> list[Any]:
        result = await self._get("/api/v1/requests/my")
        # API возвращает CarRequestListResponse {items: [...], total: int}
        if isinstance(result, dict):
            return result.get("items", [])
        return result  # type: ignore[return-value]

    async def get_available_requests(self, area: str) -> list[Any]:
        result = await self._get("/api/v1/requests/available", params={"area": area})
        if isinstance(result, dict):
            return result.get("items", [])
        return result  # type: ignore[return-value]

    async def cancel_request(self, request_id: str) -> dict[str, Any]:
        return await self._patch(f"/api/v1/requests/{request_id}/cancel")

    # ── Offers ────────────────────────────────────────────────────────────────

    async def create_offer(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/api/v1/offers", json=payload)

    async def get_offers_by_request(self, request_id: str) -> list[Any]:
        result = await self._get(f"/api/v1/offers/by-request/{request_id}")
        if isinstance(result, dict):
            return result.get("items", [])
        return result  # type: ignore[return-value]

    async def select_offer(self, offer_id: str) -> dict[str, Any]:
        return await self._patch(
            f"/api/v1/offers/{offer_id}/select",
            json={"confirm": True},
        )

    # ── Service profile ───────────────────────────────────────────────────────

    async def upsert_service_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/api/v1/service-profile", json=payload)

    async def get_my_service_profile(self) -> dict[str, Any]:
        result = await self._get("/api/v1/service-profile/me")
        return result  # type: ignore[return-value]

    # ── Offers (service side) ─────────────────────────────────────────────────

    async def get_my_offers(self) -> list[Any]:
        """GET /api/v1/offers/my — история предложений текущего сервиса."""
        result = await self._get("/api/v1/offers/my")
        if isinstance(result, dict):
            return result.get("items", [])
        return result  # type: ignore[return-value]
