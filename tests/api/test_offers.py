"""
tests/api/test_offers.py
─────────────────────────
Тесты для этапа 2.3: Offers CRUD.

Покрытие:
    POST  /api/v1/offers/                        — create_offer      (7 тестов)
    GET   /api/v1/offers/by-request/{id}         — get_offers        (5 тестов)
    PATCH /api/v1/offers/{id}/select             — select_offer      (7 тестов)
    Unit  api/services/offers.py                 — select atomicity  (3 теста)

Итого: 22 теста.

Стратегия:
    - SQLite in-memory (из conftest.py)
    - Каждый тест изолирован через savepoint
    - HTTP тесты через AsyncClient
    - Unit тесты сервиса без HTTP-слоя
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.offers import create_offer, select_offer
from api.schemas.offer import OfferCreate
from common.models.car_request import CarRequest
from common.models.enums import OfferStatusEnum, RequestStatusEnum, RoleEnum
from common.models.offer import Offer
from common.models.service_profile import ServiceProfile
from common.models.user import User
from tests.api.conftest import create_user

# ── Helpers ────────────────────────────────────────────────────────────────────

TODAY = datetime.date.today()
TOMORROW = TODAY + datetime.timedelta(days=1)


def auth_headers(telegram_id: int) -> dict[str, str]:
    return {"X-Telegram-ID": str(telegram_id)}


async def _create_car_request(
    db: AsyncSession,
    user_id: UUID,
    area: str = "Центр",
    status: RequestStatusEnum = RequestStatusEnum.CREATED,
) -> CarRequest:
    req = CarRequest(
        user_id=user_id,
        car_brand="Toyota",
        car_model="Camry",
        car_year=2020,
        description="Требуется замена масла и фильтров",
        preferred_date=TOMORROW,
        preferred_time=datetime.time(10, 0),
        area=area,
        status=status,
    )
    db.add(req)
    await db.flush()
    return req


async def _create_service_profile(
    db: AsyncSession,
    user_id: UUID,
    name: str = "АвтоМастер",
    phone: str = "+79001234567",
) -> ServiceProfile:
    profile = ServiceProfile(
        user_id=user_id,
        name=name,
        description="Профессиональный автосервис",
        areas=["Центр", "Север"],
        services=["ТО", "Тормоза"],
        phone=phone,
        is_active=True,
    )
    db.add(profile)
    await db.flush()
    return profile


async def _create_offer(
    db: AsyncSession,
    request_id: UUID,
    service_id: UUID,
    price: Decimal = Decimal("5000.00"),
    status: OfferStatusEnum = OfferStatusEnum.SENT,
) -> Offer:
    offer = Offer(
        request_id=request_id,
        service_id=service_id,
        price=price,
        comment="Оригинальные запчасти, гарантия 6 месяцев",
        proposed_date=TOMORROW,
        proposed_time=datetime.time(11, 0),
        status=status,
    )
    db.add(offer)
    await db.flush()
    return offer


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/v1/offers/
# ══════════════════════════════════════════════════════════════════════════════

class TestCreateOffer:

    async def test_create_success(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
        user_service,
    ) -> None:
        """Happy path: 201, структура ответа корректна."""
        await _create_service_profile(db_session, user_service.id)
        car_req = await _create_car_request(db_session, user_regular.id)

        resp = await client.post(
            "/api/v1/offers/",
            json={
                "request_id": str(car_req.id),
                "price": "4500.00",
                "comment": "Сделаем быстро и качественно",
            },
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert "id" in data
        assert data["status"] == "sent"

    async def test_create_unauthorized(
        self, client: AsyncClient, db_session: AsyncSession, user_regular
    ) -> None:
        """Без заголовка X-Telegram-ID → 401."""
        car_req = await _create_car_request(db_session, user_regular.id)
        resp = await client.post(
            "/api/v1/offers/",
            json={"request_id": str(car_req.id), "price": "3000.00"},
        )
        assert resp.status_code == 401

    async def test_create_wrong_role_user(
        self, client: AsyncClient, db_session: AsyncSession, user_regular
    ) -> None:
        """role=user не может создавать офферы → 403."""
        car_req = await _create_car_request(db_session, user_regular.id)
        resp = await client.post(
            "/api/v1/offers/",
            json={"request_id": str(car_req.id), "price": "3000.00"},
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 403

    async def test_create_no_service_profile(
        self, client: AsyncClient, db_session: AsyncSession, user_regular, user_service
    ) -> None:
        """Сервис без профиля → 404."""
        car_req = await _create_car_request(db_session, user_regular.id)
        resp = await client.post(
            "/api/v1/offers/",
            json={"request_id": str(car_req.id), "price": "3000.00"},
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 404

    async def test_create_request_not_found(
        self, client: AsyncClient, db_session: AsyncSession, user_service
    ) -> None:
        """Несуществующий request_id → 404."""
        await _create_service_profile(db_session, user_service.id)
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = await client.post(
            "/api/v1/offers/",
            json={"request_id": fake_id, "price": "3000.00"},
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 404

    async def test_create_terminal_request(
        self, client: AsyncClient, db_session: AsyncSession, user_regular, user_service
    ) -> None:
        """Заявка в terminal-статусе (cancelled) → 422."""
        await _create_service_profile(db_session, user_service.id)
        car_req = await _create_car_request(
            db_session, user_regular.id, status=RequestStatusEnum.CANCELLED
        )
        resp = await client.post(
            "/api/v1/offers/",
            json={"request_id": str(car_req.id), "price": "3000.00"},
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 422

    async def test_create_duplicate_conflict(
        self, client: AsyncClient, db_session: AsyncSession, user_regular, user_service
    ) -> None:
        """Повторный оффер от того же сервиса на ту же заявку → 409."""
        sp = await _create_service_profile(db_session, user_service.id)
        car_req = await _create_car_request(db_session, user_regular.id)
        # Первый оффер напрямую в БД
        await _create_offer(db_session, car_req.id, sp.id)

        resp = await client.post(
            "/api/v1/offers/",
            json={"request_id": str(car_req.id), "price": "6000.00"},
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 409


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/v1/offers/by-request/{request_id}
# ══════════════════════════════════════════════════════════════════════════════

class TestGetOffersByRequest:

    async def test_list_success(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
        user_service,
    ) -> None:
        """Happy path: владелец видит офферы по своей заявке."""
        sp = await _create_service_profile(db_session, user_service.id)
        car_req = await _create_car_request(db_session, user_regular.id)
        await _create_offer(db_session, car_req.id, sp.id)

        resp = await client.get(
            f"/api/v1/offers/by-request/{car_req.id}",
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["service_name"] == "АвтоМастер"
        assert "price" in data["items"][0]

    async def test_list_empty(
        self, client: AsyncClient, db_session: AsyncSession, user_regular
    ) -> None:
        """Заявка без офферов → пустой список, не ошибка."""
        car_req = await _create_car_request(db_session, user_regular.id)
        resp = await client.get(
            f"/api/v1/offers/by-request/{car_req.id}",
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_list_request_not_found(
        self, client: AsyncClient, user_regular
    ) -> None:
        """Несуществующий request_id → 404."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = await client.get(
            f"/api/v1/offers/by-request/{fake_id}",
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 404

    async def test_list_forbidden_other_user(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
    ) -> None:
        """Чужой пользователь не видит офферы → 403."""
        car_req = await _create_car_request(db_session, user_regular.id)
        other = await create_user(db_session, telegram_id=777_777, role=RoleEnum.USER)

        resp = await client.get(
            f"/api/v1/offers/by-request/{car_req.id}",
            headers=auth_headers(other.telegram_id),
        )
        assert resp.status_code == 403

    async def test_list_wrong_role_service(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
        user_service,
    ) -> None:
        """role=service не может смотреть офферы через этот endpoint → 403."""
        car_req = await _create_car_request(db_session, user_regular.id)
        resp = await client.get(
            f"/api/v1/offers/by-request/{car_req.id}",
            headers=auth_headers(user_service.telegram_id),
        )
        assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# PATCH /api/v1/offers/{id}/select
# ══════════════════════════════════════════════════════════════════════════════

class TestSelectOffer:

    async def test_select_success(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
        user_service,
    ) -> None:
        """Happy path: выбор оффера → 200, ответ содержит контакты сервиса."""
        sp = await _create_service_profile(db_session, user_service.id, phone="+79991112233")
        car_req = await _create_car_request(db_session, user_regular.id)
        offer = await _create_offer(db_session, car_req.id, sp.id)

        resp = await client.patch(
            f"/api/v1/offers/{offer.id}/select",
            json={"confirm": True},
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "selected"
        assert data["service_name"] == "АвтоМастер"
        assert data["service_phone"] == "+79991112233"
        assert data["offer_id"] == str(offer.id)

    async def test_select_db_state_atomic(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
        user_service,
    ) -> None:
        """
        Атомарность: выбранный оффер → selected,
        другие офферы → rejected, заявка → selected.
        """
        sp1 = await _create_service_profile(db_session, user_service.id, name="Сервис1")
        svc2_user = await create_user(db_session, telegram_id=444_444, role=RoleEnum.SERVICE)
        sp2 = await _create_service_profile(db_session, svc2_user.id, name="Сервис2", phone="+70000000002")

        car_req = await _create_car_request(db_session, user_regular.id)
        offer1 = await _create_offer(db_session, car_req.id, sp1.id, price=Decimal("4000"))
        offer2 = await _create_offer(db_session, car_req.id, sp2.id, price=Decimal("5000"))

        resp = await client.patch(
            f"/api/v1/offers/{offer1.id}/select",
            json={"confirm": True},
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 200

        # Проверяем состояние в БД
        await db_session.refresh(offer1)
        await db_session.refresh(offer2)
        await db_session.refresh(car_req)

        assert offer1.status == OfferStatusEnum.SELECTED
        assert offer2.status == OfferStatusEnum.REJECTED
        assert car_req.status == RequestStatusEnum.SELECTED

    async def test_select_offer_not_found(
        self, client: AsyncClient, user_regular
    ) -> None:
        """Несуществующий offer_id → 404."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        resp = await client.patch(
            f"/api/v1/offers/{fake_id}/select",
            json={"confirm": True},
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 404

    async def test_select_forbidden_other_user(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
        user_service,
    ) -> None:
        """Чужой пользователь не может выбрать оффер → 403."""
        sp = await _create_service_profile(db_session, user_service.id)
        car_req = await _create_car_request(db_session, user_regular.id)
        offer = await _create_offer(db_session, car_req.id, sp.id)

        other = await create_user(db_session, telegram_id=555_555, role=RoleEnum.USER)
        resp = await client.patch(
            f"/api/v1/offers/{offer.id}/select",
            json={"confirm": True},
            headers=auth_headers(other.telegram_id),
        )
        assert resp.status_code == 403

    async def test_select_already_selected(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
        user_service,
    ) -> None:
        """Повторный выбор уже selected оффера → 409."""
        sp = await _create_service_profile(db_session, user_service.id)
        car_req = await _create_car_request(db_session, user_regular.id)
        offer = await _create_offer(
            db_session, car_req.id, sp.id, status=OfferStatusEnum.SELECTED
        )

        resp = await client.patch(
            f"/api/v1/offers/{offer.id}/select",
            json={"confirm": True},
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 409

    async def test_select_rejected_offer(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
        user_service,
    ) -> None:
        """Попытка выбрать rejected оффер → 409."""
        sp = await _create_service_profile(db_session, user_service.id)
        car_req = await _create_car_request(db_session, user_regular.id)
        offer = await _create_offer(
            db_session, car_req.id, sp.id, status=OfferStatusEnum.REJECTED
        )

        resp = await client.patch(
            f"/api/v1/offers/{offer.id}/select",
            json={"confirm": True},
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 409

    async def test_select_confirm_false(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_regular,
        user_service,
    ) -> None:
        """confirm=false → 422 без выполнения операции."""
        sp = await _create_service_profile(db_session, user_service.id)
        car_req = await _create_car_request(db_session, user_regular.id)
        offer = await _create_offer(db_session, car_req.id, sp.id)

        resp = await client.patch(
            f"/api/v1/offers/{offer.id}/select",
            json={"confirm": False},
            headers=auth_headers(user_regular.telegram_id),
        )
        assert resp.status_code == 422
        # Статус оффера не изменился
        await db_session.refresh(offer)
        assert offer.status == OfferStatusEnum.SENT


# ══════════════════════════════════════════════════════════════════════════════
# Unit тесты сервиса (без HTTP)
# ══════════════════════════════════════════════════════════════════════════════

class TestOffersServiceUnit:

    async def test_create_offer_unit(
        self, db_session: AsyncSession, user_regular, user_service
    ) -> None:
        """create_offer: service_id берётся из profile, не из тела."""
        sp = await _create_service_profile(db_session, user_service.id)
        car_req = await _create_car_request(db_session, user_regular.id)

        data = OfferCreate(
            request_id=car_req.id,
            price=Decimal("3500.00"),
            comment=None,
            proposed_date=None,
            proposed_time=None,
        )
        offer = await create_offer(db_session, user_id=user_service.id, data=data)

        assert offer.service_id == sp.id
        assert offer.status == OfferStatusEnum.SENT
        assert offer.price == Decimal("3500.00")

    async def test_select_offer_updates_request_status(
        self, db_session: AsyncSession, user_regular, user_service
    ) -> None:
        """select_offer: статус заявки меняется на selected."""
        sp = await _create_service_profile(db_session, user_service.id)
        car_req = await _create_car_request(db_session, user_regular.id)
        offer = await _create_offer(db_session, car_req.id, sp.id)

        result = await select_offer(
            db_session, offer_id=offer.id, user_id=user_regular.id
        )
        assert result.offer.status == OfferStatusEnum.SELECTED
        assert result.service_profile.id == sp.id

        # Проверяем заявку через свежий запрос
        fresh_req = (await db_session.execute(
            select(CarRequest).where(CarRequest.id == car_req.id)
        )).scalar_one()
        assert fresh_req.status == RequestStatusEnum.SELECTED

    async def test_select_offer_rejects_others(
        self, db_session: AsyncSession, user_regular, user_service
    ) -> None:
        """select_offer: остальные офферы по заявке становятся rejected."""
        sp1 = await _create_service_profile(db_session, user_service.id, name="СП1")
        svc2 = await create_user(db_session, telegram_id=666_666, role=RoleEnum.SERVICE)
        sp2 = await _create_service_profile(db_session, svc2.id, name="СП2", phone="+70000000099")

        car_req = await _create_car_request(db_session, user_regular.id)
        offer1 = await _create_offer(db_session, car_req.id, sp1.id)
        offer2 = await _create_offer(db_session, car_req.id, sp2.id)

        await select_offer(db_session, offer_id=offer1.id, user_id=user_regular.id)

        fresh_offer2 = (await db_session.execute(
            select(Offer).where(Offer.id == offer2.id)
        )).scalar_one()
        assert fresh_offer2.status == OfferStatusEnum.REJECTED
