"""
tests/api/test_requests.py
───────────────────────────
Тесты для этапа 2.2: Car Requests CRUD.

Покрытие:
    POST   /api/v1/requests        — create_request (5 тестов)
    GET    /api/v1/requests/my     — get_my_requests (4 теста)
    GET    /api/v1/requests/available — get_available_requests (5 тестов)
    PATCH  /api/v1/requests/{id}/cancel — cancel_request (6 тестов)
    Unit   api/services/requests.py    — (3 теста)

Итого: 23 теста.

Стратегия:
    - SQLite in-memory (из conftest.py)
    - Каждый тест изолирован через savepoint
    - HTTP тесты через AsyncClient
    - Unit тесты сервиса без HTTP-слоя
"""

from __future__ import annotations

import datetime
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.request import CarRequestCreate
from api.services.requests import (
    cancel_request,
    create_request,
    get_available_requests,
    get_my_requests,
)
from common.models.car_request import CarRequest
from common.models.enums import RequestStatusEnum, RoleEnum
from common.models.offer import Offer
from tests.api.conftest import create_user

# ── Helpers ────────────────────────────────────────────────────────────────────

VALID_AREA = "Центр"
TODAY = datetime.date.today()
TOMORROW = TODAY + datetime.timedelta(days=1)

VALID_BODY = {
    "car_brand": "Toyota",
    "car_model": "Camry",
    "car_year": 2020,
    "description": "Замена тормозных колодок, скрип при торможении",
    "preferred_date": str(TOMORROW),
    "preferred_time": "12:00:00",
    "area": VALID_AREA,
}


def auth_headers(telegram_id: int) -> dict[str, str]:
    return {"X-Telegram-ID": str(telegram_id)}


async def _create_db_request(
    db: AsyncSession,
    user_id: UUID,
    area: str = VALID_AREA,
    status: RequestStatusEnum = RequestStatusEnum.CREATED,
) -> CarRequest:
    """Вспомогательная функция: создать заявку напрямую в БД."""
    req = CarRequest(
        user_id=user_id,
        car_brand="BMW",
        car_model="X5",
        car_year=2019,
        description="Требуется замена масла и фильтров",
        preferred_date=TOMORROW,
        preferred_time=datetime.time(10, 0),
        area=area,
        status=status,
    )
    db.add(req)
    await db.flush()
    return req


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/requests
# ══════════════════════════════════════════════════════════════════════════════

class TestCreateRequest:

    async def test_create_success(
        self, client: AsyncClient, user_regular
    ) -> None:
        """Happy path: 201, проверяем структуру ответа."""
        resp = await client.post(
            "/api/v1/requests/",
            json=VALID_BODY,
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "id" in data
        assert data["status"] == "created"
        assert "created_at" in data

    async def test_create_unauthorized(self, client: AsyncClient) -> None:
        """Без заголовка X-Telegram-ID → 401."""
        resp = await client.post("/api/v1/requests/", json=VALID_BODY)
        assert resp.status_code == 401

    async def test_create_wrong_role_service(
        self, client: AsyncClient, user_service
    ) -> None:
        """role=service не может создавать заявки → 403."""
        resp = await client.post(
            "/api/v1/requests/",
            json=VALID_BODY,
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 403

    async def test_create_invalid_area(
        self, client: AsyncClient, user_regular
    ) -> None:
        """Район не из allowed_areas → 422."""
        body = {**VALID_BODY, "area": "НесуществующийРайон"}
        resp = await client.post(
            "/api/v1/requests/",
            json=body,
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 422

    async def test_create_date_in_past(
        self, client: AsyncClient, user_regular
    ) -> None:
        """preferred_date в прошлом → 422 (валидация схемы)."""
        yesterday = str(TODAY - datetime.timedelta(days=1))
        body = {**VALID_BODY, "preferred_date": yesterday}
        resp = await client.post(
            "/api/v1/requests/",
            json=body,
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 422

    async def test_create_db_state(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
    ) -> None:
        """После создания: запись реально есть в БД с нужными полями."""
        resp = await client.post(
            "/api/v1/requests/",
            json=VALID_BODY,
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 201
        request_id = UUID(resp.json()["id"])

        from sqlalchemy import select
        row = (await db_session.execute(
            select(CarRequest).where(CarRequest.id == request_id)
        )).scalar_one_or_none()

        assert row is not None
        assert row.user_id == user_regular.id
        assert row.area == VALID_AREA
        assert row.status == RequestStatusEnum.CREATED
        assert row.car_brand == "Toyota"


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/requests/my
# ══════════════════════════════════════════════════════════════════════════════

class TestMyRequests:

    async def test_my_requests_empty(
        self, client: AsyncClient, user_regular
    ) -> None:
        """У нового пользователя нет заявок → пустой список."""
        resp = await client.get(
            "/api/v1/requests/my",
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_my_requests_returns_own_only(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
        user_admin,
    ) -> None:
        """Пользователь видит только свои заявки, чужие не попадают."""
        # Создаём заявку нашего юзера
        await _create_db_request(db_session, user_regular.id)
        # И чужую заявку (admin пусть тоже будет user для этого теста)
        other = await create_user(db_session, telegram_id=999_999, role=RoleEnum.USER)
        await _create_db_request(db_session, other.id)

        resp = await client.get(
            "/api/v1/requests/my",
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1

    async def test_my_requests_offers_count(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
        user_service,
    ) -> None:
        """offers_count корректно считается через подзапрос."""
        req = await _create_db_request(db_session, user_regular.id)
        # Добавляем оффер напрямую
        offer = Offer(
            request_id=req.id,
            service_id=user_service.id,
            price=5000,
            comment="Готовы сделать",
            proposed_date=TOMORROW,
            proposed_time=datetime.time(11, 0),
        )
        db_session.add(offer)
        await db_session.flush()

        resp = await client.get(
            "/api/v1/requests/my",
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        assert item["offers_count"] == 1

    async def test_my_requests_unauthorized(self, client: AsyncClient) -> None:
        """Без X-Telegram-ID → 401."""
        resp = await client.get("/api/v1/requests/my")
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/requests/available
# ══════════════════════════════════════════════════════════════════════════════

class TestAvailableRequests:

    async def test_available_returns_active_only(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
        user_service,
    ) -> None:
        """Terminal-статусы (done, cancelled) не попадают в результат."""
        await _create_db_request(db_session, user_regular.id, status=RequestStatusEnum.CREATED)
        await _create_db_request(db_session, user_regular.id, status=RequestStatusEnum.CANCELLED)
        await _create_db_request(db_session, user_regular.id, status=RequestStatusEnum.DONE)

        resp = await client.get(
            "/api/v1/requests/available",
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    async def test_available_filter_by_area(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
        user_service,
    ) -> None:
        """Фильтр по area возвращает только нужный район."""
        await _create_db_request(db_session, user_regular.id, area="Центр")
        await _create_db_request(db_session, user_regular.id, area="Север")

        resp = await client.get(
            "/api/v1/requests/available?area=Север",
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["area"] == "Север"

    async def test_available_invalid_area(
        self,
        client: AsyncClient,
        user_service,
    ) -> None:
        """Недопустимый area-фильтр → 422."""
        resp = await client.get(
            "/api/v1/requests/available?area=НетТакогоРайона",
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 422

    async def test_available_wrong_role_user(
        self,
        client: AsyncClient,
        user_regular,
    ) -> None:
        """role=user не может смотреть available → 403."""
        resp = await client.get(
            "/api/v1/requests/available",
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 403

    async def test_available_unauthorized(self, client: AsyncClient) -> None:
        """Без X-Telegram-ID → 401."""
        resp = await client.get("/api/v1/requests/available")
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# PATCH /api/v1/requests/{id}/cancel
# ══════════════════════════════════════════════════════════════════════════════

class TestCancelRequest:

    async def test_cancel_success(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
    ) -> None:
        """Happy path: заявка со статусом created → cancelled."""
        req = await _create_db_request(db_session, user_regular.id)
        resp = await client.patch(
            f"/api/v1/requests/{req.id}/cancel",
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    async def test_cancel_db_state(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
    ) -> None:
        """После отмены: статус в БД действительно cancelled."""
        from sqlalchemy import select
        req = await _create_db_request(db_session, user_regular.id)
        resp = await client.patch(
            f"/api/v1/requests/{req.id}/cancel",
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 200
        await db_session.refresh(req)
        assert req.status == RequestStatusEnum.CANCELLED

    async def test_cancel_not_found(
        self, client: AsyncClient, user_regular
    ) -> None:
        """Несуществующий request_id → 404."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = await client.patch(
            f"/api/v1/requests/{fake_id}/cancel",
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 404

    async def test_cancel_forbidden_other_user(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
    ) -> None:
        """Чужой пользователь не может отменить заявку → 403."""
        other = await create_user(db_session, telegram_id=888_888, role=RoleEnum.USER)
        req = await _create_db_request(db_session, user_regular.id)

        resp = await client.patch(
            f"/api/v1/requests/{req.id}/cancel",
            headers=auth_headers(other.telegram_id),
        )
        assert resp.status_code == 403

    async def test_cancel_invalid_status_offers(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
    ) -> None:
        """Заявка в статусе offers теперь МОЖЕТ быть отменена (исправлен баг) → 200."""
        req = await _create_db_request(
            db_session, user_regular.id, status=RequestStatusEnum.OFFERS
        )
        resp = await client.patch(
            f"/api/v1/requests/{req.id}/cancel",
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

    async def test_cancel_offers_db_state(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
    ) -> None:
        """После отмены из OFFERS: статус в БД = cancelled."""
        req = await _create_db_request(
            db_session, user_regular.id, status=RequestStatusEnum.OFFERS
        )
        await client.patch(
            f"/api/v1/requests/{req.id}/cancel",
            headers=auth_headers(user_regular.telegram_id),
        )
        await db_session.refresh(req)
        assert req.status == RequestStatusEnum.CANCELLED

    async def test_cancel_invalid_status_selected(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
    ) -> None:
        """Заявка в статусе selected не может быть отменена → 422."""
        req = await _create_db_request(
            db_session, user_regular.id, status=RequestStatusEnum.SELECTED
        )
        resp = await client.patch(
            f"/api/v1/requests/{req.id}/cancel",
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# Unit тесты сервиса (без HTTP)
# ══════════════════════════════════════════════════════════════════════════════

class TestRequestsServiceUnit:

    async def test_create_request_sets_user_id(
        self, db_session: AsyncSession, user_regular
    ) -> None:
        """create_request: user_id берётся из аргумента, не из тела."""
        data = CarRequestCreate(
            car_brand="Honda",
            car_model="Civic",
            car_year=2021,
            description="Проблема с двигателем, странный звук на холостом ходу",
            preferred_date=TOMORROW,
            preferred_time=datetime.time(9, 0),
            area=VALID_AREA,
        )
        req = await create_request(db_session, user_id=user_regular.id, data=data)
        assert req.user_id == user_regular.id
        assert req.status == RequestStatusEnum.CREATED

    async def test_get_available_excludes_terminal(
        self, db_session: AsyncSession, user_regular
    ) -> None:
        """get_available_requests: terminal-статусы не возвращаются."""
        await _create_db_request(db_session, user_regular.id, status=RequestStatusEnum.CREATED)
        await _create_db_request(db_session, user_regular.id, status=RequestStatusEnum.DONE)

        result = await get_available_requests(db_session)
        assert all(
            r.status not in RequestStatusEnum.terminal_states()
            for r in result
        )

    async def test_cancel_request_unit(
        self, db_session: AsyncSession, user_regular
    ) -> None:
        """cancel_request unit: меняет статус напрямую через сервис."""
        req = await _create_db_request(db_session, user_regular.id)
        cancelled = await cancel_request(
            db_session, request_id=req.id, user_id=user_regular.id
        )
        assert cancelled.status == RequestStatusEnum.CANCELLED

    async def test_cancel_request_from_offers_status(
        self, db_session: AsyncSession, user_regular
    ) -> None:
        """cancel_request из OFFERS — допустимо (исправлен баг #3)."""
        req = await _create_db_request(
            db_session, user_regular.id, status=RequestStatusEnum.OFFERS
        )
        cancelled = await cancel_request(
            db_session, request_id=req.id, user_id=user_regular.id
        )
        assert cancelled.status == RequestStatusEnum.CANCELLED

    async def test_cancel_request_from_selected_fails(
        self, db_session: AsyncSession, user_regular
    ) -> None:
        """cancel_request из SELECTED — нельзя (terminal-like статус)."""
        from api.exceptions import InvalidStatusError
        req = await _create_db_request(
            db_session, user_regular.id, status=RequestStatusEnum.SELECTED
        )
        with pytest.raises(InvalidStatusError):
            await cancel_request(db_session, request_id=req.id, user_id=user_regular.id)
