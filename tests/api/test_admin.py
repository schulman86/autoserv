"""
tests/api/test_admin.py
────────────────────────
Тесты для этапа 2.6: Admin API.

Покрытие:
    GET   /api/v1/admin/requests        — list_requests      (5 тестов)
    GET   /api/v1/admin/users           — list_users         (5 тестов)
    PATCH /api/v1/admin/users/{id}/block — block_user        (7 тестов)
    GET   /api/v1/admin/stats           — stats              (4 теста)
    is_blocked в current_user dep       — blocked → 401      (2 теста)
    Unit: api/services/admin.py                              (4 теста)

Итого: 27 тестов.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.admin import block_user, get_admin_requests, get_stats
from common.models.car_request import CarRequest
from common.models.enums import OfferStatusEnum, RequestStatusEnum, RoleEnum
from common.models.offer import Offer
from common.models.service_profile import ServiceProfile
from common.models.user import User
from tests.api.conftest import create_user

# ── Helpers ────────────────────────────────────────────────────────────────────


def auth(telegram_id: int) -> dict[str, str]:
    return {"X-Telegram-ID": str(telegram_id)}


async def make_request(
    db: AsyncSession,
    user_id,
    area: str = "Центр",
    status: RequestStatusEnum = RequestStatusEnum.CREATED,
) -> CarRequest:
    req = CarRequest(
        user_id=user_id,
        car_brand="Toyota",
        car_model="Camry",
        car_year=2020,
        description="Тестовая заявка описание",
        preferred_date=datetime.date.today() + datetime.timedelta(days=5),
        preferred_time=datetime.time(10, 0),
        area=area,
        status=status,
    )
    db.add(req)
    await db.flush()
    return req


async def make_service_with_profile(
    db: AsyncSession, telegram_id: int
) -> tuple[User, ServiceProfile]:
    user = await create_user(db, telegram_id, RoleEnum.SERVICE)
    sp = ServiceProfile(
        user_id=user.id,
        name=f"Сервис {telegram_id}",
        areas=["Центр"],
        services=["ТО"],
        phone=f"+7900{telegram_id % 10000000:07d}",
        is_active=True,
    )
    db.add(sp)
    await db.flush()
    return user, sp


async def make_offer(db: AsyncSession, request_id, service_id) -> Offer:
    offer = Offer(
        request_id=request_id,
        service_id=service_id,
        price=Decimal("3000.00"),
        status=OfferStatusEnum.SENT,
    )
    db.add(offer)
    await db.flush()
    return offer


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/admin/requests
# ══════════════════════════════════════════════════════════════════════════════


class TestAdminListRequests:

    async def test_list_all_requests(
        self, client: AsyncClient, db_session: AsyncSession, user_admin
    ) -> None:
        """Happy path: возвращает все заявки с offers_count."""
        user = await create_user(db_session, 100001, RoleEnum.USER)
        req = await make_request(db_session, user.id)

        resp = await client.get(
            "/api/v1/admin/requests",
            headers=auth(user_admin.telegram_id),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] >= 1
        ids = [item["id"] for item in data["items"]]
        assert str(req.id) in ids

    async def test_filter_by_status(
        self, client: AsyncClient, db_session: AsyncSession, user_admin
    ) -> None:
        """Фильтр по status работает корректно."""
        user = await create_user(db_session, 100002, RoleEnum.USER)
        await make_request(db_session, user.id, status=RequestStatusEnum.CREATED)
        cancelled = await make_request(
            db_session, user.id, status=RequestStatusEnum.CANCELLED
        )

        resp = await client.get(
            "/api/v1/admin/requests?status=cancelled",
            headers=auth(user_admin.telegram_id),
        )
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["items"]]
        assert str(cancelled.id) in ids
        # Все в ответе — cancelled
        for item in resp.json()["items"]:
            assert item["status"] == "cancelled"

    async def test_filter_by_area(
        self, client: AsyncClient, db_session: AsyncSession, user_admin
    ) -> None:
        """Фильтр по area работает корректно."""
        user = await create_user(db_session, 100003, RoleEnum.USER)
        north_req = await make_request(db_session, user.id, area="Север")
        await make_request(db_session, user.id, area="Юг")

        resp = await client.get(
            "/api/v1/admin/requests?area=Север",
            headers=auth(user_admin.telegram_id),
        )
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()["items"]]
        assert str(north_req.id) in ids
        for item in resp.json()["items"]:
            assert item["area"] == "Север"

    async def test_offers_count_in_response(
        self, client: AsyncClient, db_session: AsyncSession, user_admin
    ) -> None:
        """offers_count корректно считается через JOIN."""
        user = await create_user(db_session, 100004, RoleEnum.USER)
        _, sp = await make_service_with_profile(db_session, 100005)
        req = await make_request(db_session, user.id)
        await make_offer(db_session, req.id, sp.id)

        resp = await client.get(
            "/api/v1/admin/requests",
            headers=auth(user_admin.telegram_id),
        )
        assert resp.status_code == 200
        item = next(i for i in resp.json()["items"] if i["id"] == str(req.id))
        assert item["offers_count"] == 1

    async def test_forbidden_for_non_admin(
        self, client: AsyncClient, user_regular
    ) -> None:
        """role=user → 403."""
        resp = await client.get(
            "/api/v1/admin/requests",
            headers=auth(user_regular.telegram_id),
        )
        assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/admin/users
# ══════════════════════════════════════════════════════════════════════════════


class TestAdminListUsers:

    async def test_list_users_structure(
        self, client: AsyncClient, db_session: AsyncSession, user_admin
    ) -> None:
        """Ответ содержит правильную структуру с пагинацией."""
        resp = await client.get(
            "/api/v1/admin/users",
            headers=auth(user_admin.telegram_id),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert data["page"] == 1

    async def test_includes_is_blocked_field(
        self, client: AsyncClient, db_session: AsyncSession, user_admin
    ) -> None:
        """Каждый пользователь содержит поле is_blocked."""
        await create_user(db_session, 200001, RoleEnum.USER)
        resp = await client.get(
            "/api/v1/admin/users",
            headers=auth(user_admin.telegram_id),
        )
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert "is_blocked" in item

    async def test_pagination_page_size(
        self, client: AsyncClient, db_session: AsyncSession, user_admin
    ) -> None:
        """page_size ограничивает число результатов."""
        for i in range(5):
            await create_user(db_session, 200100 + i, RoleEnum.USER)

        resp = await client.get(
            "/api/v1/admin/users?page=1&page_size=2",
            headers=auth(user_admin.telegram_id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 2
        assert data["page_size"] == 2

    async def test_pagination_second_page(
        self, client: AsyncClient, db_session: AsyncSession, user_admin
    ) -> None:
        """Вторая страница возвращает другой набор пользователей."""
        for i in range(4):
            await create_user(db_session, 200200 + i, RoleEnum.USER)

        resp1 = await client.get(
            "/api/v1/admin/users?page=1&page_size=2",
            headers=auth(user_admin.telegram_id),
        )
        resp2 = await client.get(
            "/api/v1/admin/users?page=2&page_size=2",
            headers=auth(user_admin.telegram_id),
        )
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        ids1 = {i["id"] for i in resp1.json()["items"]}
        ids2 = {i["id"] for i in resp2.json()["items"]}
        # Страницы не пересекаются
        assert ids1.isdisjoint(ids2)

    async def test_unauthorized_no_header(self, client: AsyncClient) -> None:
        """Без заголовка → 401."""
        resp = await client.get("/api/v1/admin/users")
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# PATCH /api/v1/admin/users/{id}/block
# ══════════════════════════════════════════════════════════════════════════════


class TestAdminBlockUser:

    async def test_block_user_success(
        self, client: AsyncClient, db_session: AsyncSession, user_admin
    ) -> None:
        """Happy path: пользователь заблокирован, is_blocked=True."""
        target = await create_user(db_session, 300001, RoleEnum.USER)
        resp = await client.patch(
            f"/api/v1/admin/users/{target.id}/block?block=true",
            headers=auth(user_admin.telegram_id),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_blocked"] is True

    async def test_unblock_user_success(
        self, client: AsyncClient, db_session: AsyncSession, user_admin
    ) -> None:
        """Разблокировка: is_blocked=False."""
        target = await create_user(db_session, 300002, RoleEnum.USER)
        target.is_blocked = True
        await db_session.flush()

        resp = await client.patch(
            f"/api/v1/admin/users/{target.id}/block?block=false",
            headers=auth(user_admin.telegram_id),
        )
        assert resp.status_code == 200
        assert resp.json()["is_blocked"] is False

    async def test_block_persisted_in_db(
        self, client: AsyncClient, db_session: AsyncSession, user_admin
    ) -> None:
        """После блокировки is_blocked=True в БД."""
        target = await create_user(db_session, 300003, RoleEnum.USER)
        await client.patch(
            f"/api/v1/admin/users/{target.id}/block?block=true",
            headers=auth(user_admin.telegram_id),
        )
        await db_session.refresh(target)
        assert target.is_blocked is True

    async def test_cannot_block_self(
        self, client: AsyncClient, db_session: AsyncSession, user_admin
    ) -> None:
        """Нельзя заблокировать самого себя → 403."""
        resp = await client.patch(
            f"/api/v1/admin/users/{user_admin.id}/block?block=true",
            headers=auth(user_admin.telegram_id),
        )
        assert resp.status_code == 403

    async def test_cannot_block_another_admin(
        self, client: AsyncClient, db_session: AsyncSession, user_admin
    ) -> None:
        """Нельзя заблокировать другого admin → 403."""
        admin2 = await create_user(db_session, 300004, RoleEnum.ADMIN)
        resp = await client.patch(
            f"/api/v1/admin/users/{admin2.id}/block?block=true",
            headers=auth(user_admin.telegram_id),
        )
        assert resp.status_code == 403

    async def test_block_not_found(
        self, client: AsyncClient, db_session: AsyncSession, user_admin
    ) -> None:
        """Несуществующий пользователь → 404."""
        from uuid import uuid4
        resp = await client.patch(
            f"/api/v1/admin/users/{uuid4()}/block?block=true",
            headers=auth(user_admin.telegram_id),
        )
        assert resp.status_code == 404

    async def test_block_forbidden_for_non_admin(
        self, client: AsyncClient, db_session: AsyncSession, user_regular
    ) -> None:
        """role=user → 403."""
        target = await create_user(db_session, 300005, RoleEnum.USER)
        resp = await client.patch(
            f"/api/v1/admin/users/{target.id}/block?block=true",
            headers=auth(user_regular.telegram_id),
        )
        assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/admin/stats
# ══════════════════════════════════════════════════════════════════════════════


class TestAdminStats:

    async def test_stats_structure(
        self, client: AsyncClient, db_session: AsyncSession, user_admin
    ) -> None:
        """Ответ содержит все обязательные поля."""
        resp = await client.get(
            "/api/v1/admin/stats",
            headers=auth(user_admin.telegram_id),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "total_requests" in data
        assert "total_users" in data
        assert "total_services" in data
        assert "conversion_rate" in data
        assert "avg_offers_per_request" in data
        assert "requests_by_status" in data

    async def test_stats_all_statuses_present(
        self, client: AsyncClient, db_session: AsyncSession, user_admin
    ) -> None:
        """requests_by_status содержит все статусы (включая нулевые)."""
        resp = await client.get(
            "/api/v1/admin/stats",
            headers=auth(user_admin.telegram_id),
        )
        assert resp.status_code == 200
        by_status = resp.json()["requests_by_status"]
        for status in ("created", "offers", "selected", "done", "cancelled"):
            assert status in by_status

    async def test_stats_conversion_rate(
        self, client: AsyncClient, db_session: AsyncSession, user_admin
    ) -> None:
        """Конверсия считается корректно: с оффером / всего."""
        user = await create_user(db_session, 400001, RoleEnum.USER)
        _, sp = await make_service_with_profile(db_session, 400002)
        req_with_offer = await make_request(db_session, user.id)
        await make_request(db_session, user.id)  # без оффера
        await make_offer(db_session, req_with_offer.id, sp.id)

        resp = await client.get(
            "/api/v1/admin/stats",
            headers=auth(user_admin.telegram_id),
        )
        data = resp.json()
        # conversion_rate = (заявки с офферами) / total_requests
        # Должно быть > 0 и <= 1
        assert 0.0 < data["conversion_rate"] <= 1.0

    async def test_stats_empty_db(
        self, client: AsyncClient, db_session: AsyncSession, user_admin
    ) -> None:
        """При пустой БД метрики = 0, нет ошибок деления на ноль."""
        resp = await client.get(
            "/api/v1/admin/stats",
            headers=auth(user_admin.telegram_id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["conversion_rate"] == 0.0
        assert data["avg_offers_per_request"] == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# is_blocked → 401 в current_user dependency
# ══════════════════════════════════════════════════════════════════════════════


class TestBlockedUserAccessDenied:

    async def test_blocked_user_gets_401(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Заблокированный пользователь получает 401 на любом защищённом эндпоинте."""
        blocked = await create_user(db_session, 500001, RoleEnum.USER)
        blocked.is_blocked = True
        await db_session.flush()

        resp = await client.get(
            "/api/v1/requests/my",
            headers=auth(blocked.telegram_id),
        )
        assert resp.status_code == 401
        assert "blocked" in resp.json()["detail"].lower()

    async def test_unblocked_user_gets_access(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """После разблокировки пользователь снова получает доступ."""
        user = await create_user(db_session, 500002, RoleEnum.USER)
        user.is_blocked = True
        await db_session.flush()

        # Заблокирован → 401
        resp1 = await client.get(
            "/api/v1/requests/my",
            headers=auth(user.telegram_id),
        )
        assert resp1.status_code == 401

        # Разблокируем
        user.is_blocked = False
        await db_session.flush()

        # Теперь доступ есть
        resp2 = await client.get(
            "/api/v1/requests/my",
            headers=auth(user.telegram_id),
        )
        assert resp2.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# Unit: api/services/admin.py
# ══════════════════════════════════════════════════════════════════════════════


class TestAdminServiceUnit:

    async def test_get_admin_requests_filter_status(
        self, db_session: AsyncSession
    ) -> None:
        """get_admin_requests фильтрует по статусу корректно."""
        user = await create_user(db_session, 600001, RoleEnum.USER)
        created = await make_request(db_session, user.id, status=RequestStatusEnum.CREATED)
        cancelled = await make_request(db_session, user.id, status=RequestStatusEnum.CANCELLED)

        result = await get_admin_requests(db_session, status=RequestStatusEnum.CREATED)
        ids = [r.request.id for r in result]
        assert created.id in ids
        assert cancelled.id not in ids

    async def test_get_stats_zero_division_safe(
        self, db_session: AsyncSession
    ) -> None:
        """get_stats: нет деления на ноль при пустой БД."""
        result = await get_stats(db_session)
        assert result.total_requests == 0
        assert result.conversion_rate == 0.0
        assert result.avg_offers_per_request == 0.0

    async def test_block_user_unit(self, db_session: AsyncSession) -> None:
        """block_user: устанавливает is_blocked=True."""
        admin = await create_user(db_session, 600002, RoleEnum.ADMIN)
        target = await create_user(db_session, 600003, RoleEnum.USER)

        updated = await block_user(
            db_session,
            target_user_id=target.id,
            admin_user_id=admin.id,
            block=True,
        )
        assert updated.is_blocked is True

    async def test_block_user_cannot_block_self(
        self, db_session: AsyncSession
    ) -> None:
        """block_user: ForbiddenError при попытке заблокировать себя."""
        from api.exceptions import ForbiddenError as AppForbidden
        admin = await create_user(db_session, 600004, RoleEnum.ADMIN)

        with pytest.raises(AppForbidden):
            await block_user(
                db_session,
                target_user_id=admin.id,
                admin_user_id=admin.id,
                block=True,
            )
