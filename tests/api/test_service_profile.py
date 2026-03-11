"""
tests/api/test_service_profile.py
───────────────────────────────────
Тесты для этапа 2.4: Service Profile upsert + get.

Покрытие:
    POST /api/v1/service-profile/    — upsert_profile  (7 тестов)
    GET  /api/v1/service-profile/me  — get_my_profile  (4 теста)
    Unit api/services/service_profile.py               (3 теста)

Итого: 14 тестов.

Стратегия:
    - SQLite in-memory (из conftest.py)
    - Каждый тест изолирован через savepoint
    - HTTP тесты через AsyncClient
    - Unit тесты сервиса без HTTP-слоя
"""

from __future__ import annotations

from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.service_profile import get_my_profile, upsert_profile
from api.schemas.service_profile import ServiceProfileUpsert
from common.models.enums import RoleEnum
from common.models.service_profile import ServiceProfile
from tests.api.conftest import create_user

# ── Helpers ────────────────────────────────────────────────────────────────────

VALID_BODY = {
    "name": "АвтоМастер",
    "description": "Профессиональный сервис с 2010 года",
    "areas": ["Центр", "Север"],
    "services": ["ТО", "Тормоза"],
    "phone": "+79001234567",
}


def auth_headers(telegram_id: int) -> dict[str, str]:
    return {"X-Telegram-ID": str(telegram_id)}


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/service-profile/
# ══════════════════════════════════════════════════════════════════════════════

class TestUpsertProfile:

    async def test_create_success(
        self, client: AsyncClient, user_service
    ) -> None:
        """Happy path: 200, профиль создан, структура ответа корректна."""
        resp = await client.post(
            "/api/v1/service-profile/",
            json=VALID_BODY,
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["name"] == "АвтоМастер"
        assert data["areas"] == ["Центр", "Север"]
        assert data["services"] == ["ТО", "Тормоза"]
        assert data["phone"] == "+79001234567"
        assert data["is_active"] is True
        assert "id" in data
        assert "user_id" in data
        assert "created_at" in data

    async def test_update_idempotent(
        self, client: AsyncClient, user_service
    ) -> None:
        """Повторный POST обновляет существующий профиль (idempotent)."""
        # Первый вызов — создание
        resp1 = await client.post(
            "/api/v1/service-profile/",
            json=VALID_BODY,
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp1.status_code == 200
        original_id = resp1.json()["id"]

        # Второй вызов — обновление
        updated_body = {**VALID_BODY, "name": "Новое название", "areas": ["Юг"]}
        resp2 = await client.post(
            "/api/v1/service-profile/",
            json=updated_body,
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp2.status_code == 200
        data = resp2.json()
        # id не изменился — тот же профиль
        assert data["id"] == original_id
        assert data["name"] == "Новое название"
        assert data["areas"] == ["Юг"]

    async def test_create_db_state(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_service,
    ) -> None:
        """После создания: запись реально есть в БД с правильными полями."""
        resp = await client.post(
            "/api/v1/service-profile/",
            json=VALID_BODY,
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 200

        row = (await db_session.execute(
            select(ServiceProfile).where(ServiceProfile.user_id == user_service.id)
        )).scalar_one_or_none()

        assert row is not None
        assert row.name == "АвтоМастер"
        assert row.phone == "+79001234567"
        assert row.is_active is True

    async def test_unauthorized(self, client: AsyncClient) -> None:
        """Без X-Telegram-ID → 401."""
        resp = await client.post("/api/v1/service-profile/", json=VALID_BODY)
        assert resp.status_code == 401

    async def test_wrong_role_user(
        self, client: AsyncClient, user_regular
    ) -> None:
        """role=user не может создавать профиль сервиса → 403."""
        resp = await client.post(
            "/api/v1/service-profile/",
            json=VALID_BODY,
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 403

    async def test_invalid_area(
        self, client: AsyncClient, user_service
    ) -> None:
        """Район не из allowed_areas → 422."""
        body = {**VALID_BODY, "areas": ["НесуществующийРайон"]}
        resp = await client.post(
            "/api/v1/service-profile/",
            json=body,
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 422

    async def test_empty_areas_list(
        self, client: AsyncClient, user_service
    ) -> None:
        """Пустой список areas → 422 (валидация схемы)."""
        body = {**VALID_BODY, "areas": []}
        resp = await client.post(
            "/api/v1/service-profile/",
            json=body,
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 422

    async def test_empty_services_list(
        self, client: AsyncClient, user_service
    ) -> None:
        """Пустой список services → 422 (валидация схемы)."""
        body = {**VALID_BODY, "services": []}
        resp = await client.post(
            "/api/v1/service-profile/",
            json=body,
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 422

    async def test_invalid_phone_format(
        self, client: AsyncClient, user_service
    ) -> None:
        """Неверный формат телефона → 422 (валидация схемы)."""
        body = {**VALID_BODY, "phone": "89001234567"}  # без +7
        resp = await client.post(
            "/api/v1/service-profile/",
            json=body,
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 422

    async def test_description_optional(
        self, client: AsyncClient, user_service
    ) -> None:
        """description опционален — можно создать без него."""
        body = {k: v for k, v in VALID_BODY.items() if k != "description"}
        resp = await client.post(
            "/api/v1/service-profile/",
            json=body,
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 200
        assert resp.json()["description"] is None

    async def test_update_does_not_change_is_active(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_service,
    ) -> None:
        """Обновление не меняет is_active (может быть деактивирован admin'ом)."""
        # Создаём профиль напрямую с is_active=False (как будто admin деактивировал)
        profile = ServiceProfile(
            user_id=user_service.id,
            name="Старое имя",
            areas=["Центр"],
            services=["ТО"],
            phone="+79000000000",
            is_active=False,
        )
        db_session.add(profile)
        await db_session.flush()

        # Upsert через API
        resp = await client.post(
            "/api/v1/service-profile/",
            json=VALID_BODY,
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 200

        await db_session.refresh(profile)
        # is_active остался False — upsert не трогает это поле
        assert profile.is_active is False


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/service-profile/me
# ══════════════════════════════════════════════════════════════════════════════

class TestGetMyProfile:

    async def test_get_success(
        self, client: AsyncClient, db_session: AsyncSession, user_service
    ) -> None:
        """Happy path: профиль существует → 200 с корректной структурой."""
        profile = ServiceProfile(
            user_id=user_service.id,
            name="МойСервис",
            areas=["Восток"],
            services=["Подвеска"],
            phone="+79009876543",
            is_active=True,
        )
        db_session.add(profile)
        await db_session.flush()

        resp = await client.get(
            "/api/v1/service-profile/me",
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["name"] == "МойСервис"
        assert data["areas"] == ["Восток"]
        assert data["user_id"] == str(user_service.id)

    async def test_get_not_found(
        self, client: AsyncClient, user_service
    ) -> None:
        """Профиль ещё не создан → 404."""
        resp = await client.get(
            "/api/v1/service-profile/me",
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 404

    async def test_get_unauthorized(self, client: AsyncClient) -> None:
        """Без X-Telegram-ID → 401."""
        resp = await client.get("/api/v1/service-profile/me")
        assert resp.status_code == 401

    async def test_get_wrong_role_user(
        self, client: AsyncClient, user_regular
    ) -> None:
        """role=user не имеет доступа → 403."""
        resp = await client.get(
            "/api/v1/service-profile/me",
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# Unit тесты сервиса (без HTTP)
# ══════════════════════════════════════════════════════════════════════════════

class TestServiceProfileServiceUnit:

    async def test_upsert_creates_new(
        self, db_session: AsyncSession, user_service
    ) -> None:
        """upsert_profile: is_new=True при создании."""
        data = ServiceProfileUpsert(
            name="Тест",
            areas=["Центр"],
            services=["ТО"],
            phone="+79001110000",
        )
        profile, is_new = await upsert_profile(db_session, user_id=user_service.id, data=data)
        assert is_new is True
        assert profile.user_id == user_service.id
        assert profile.name == "Тест"

    async def test_upsert_updates_existing(
        self, db_session: AsyncSession, user_service
    ) -> None:
        """upsert_profile: is_new=False при обновлении, id не меняется."""
        data1 = ServiceProfileUpsert(
            name="Первое",
            areas=["Центр"],
            services=["ТО"],
            phone="+79001110001",
        )
        profile1, is_new1 = await upsert_profile(db_session, user_id=user_service.id, data=data1)
        assert is_new1 is True
        original_id = profile1.id

        data2 = ServiceProfileUpsert(
            name="Второе",
            areas=["Север"],
            services=["Тормоза"],
            phone="+79001110002",
        )
        profile2, is_new2 = await upsert_profile(db_session, user_id=user_service.id, data=data2)
        assert is_new2 is False
        assert profile2.id == original_id
        assert profile2.name == "Второе"
        assert profile2.areas == ["Север"]

    async def test_get_my_profile_not_found(
        self, db_session: AsyncSession, user_service
    ) -> None:
        """get_my_profile: NotFoundError если профиль отсутствует."""
        from api.exceptions import NotFoundError
        with pytest.raises(NotFoundError):
            await get_my_profile(db_session, user_id=user_service.id)
