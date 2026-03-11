"""
tests/api/test_notifications.py
─────────────────────────────────
Тесты для api/services/notifications.py (после рефакторинга на UUID-API).

Все notify_* теперь принимают UUID вместо ORM-объектов.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.services.notifications import (
    _send_notification,
    notify_service_offer_selected,
    notify_services_new_request,
    notify_user_new_offer,
)
from common.models.car_request import CarRequest
from common.models.enums import OfferStatusEnum, RequestStatusEnum, RoleEnum
from common.models.offer import Offer
from common.models.service_profile import ServiceProfile
from common.models.user import User
from tests.api.conftest import create_user


# ── Helpers ────────────────────────────────────────────────────────────────────

REQUEST_BODY = {
    "car_brand": "Toyota",
    "car_model": "Camry",
    "car_year": 2020,
    "description": "Замена тормозных колодок",
    "preferred_date": str(datetime.date.today() + datetime.timedelta(days=3)),
    "preferred_time": "12:00:00",
    "area": "Центр",
}

OFFER_BODY = {"price": "4500.00", "comment": "Оригинальные колодки"}


def auth(tid: int) -> dict[str, str]:
    return {"X-Telegram-ID": str(tid)}


async def _make_service(db: AsyncSession, tid: int, areas: list[str]) -> tuple[User, ServiceProfile]:
    user = await create_user(db, tid, RoleEnum.SERVICE)
    sp = ServiceProfile(
        user_id=user.id, name=f"Сервис {tid}", areas=areas,
        services=["ТО"], phone=f"+7900{tid % 10000000:07d}", is_active=True,
    )
    db.add(sp)
    await db.flush()
    return user, sp


async def _make_request(db: AsyncSession, user_id: UUID, area: str = "Центр") -> CarRequest:
    r = CarRequest(
        user_id=user_id, car_brand="Toyota", car_model="Camry", car_year=2020,
        description="Тест уведомлений",
        preferred_date=datetime.date.today() + datetime.timedelta(days=3),
        preferred_time=datetime.time(12, 0),
        area=area, status=RequestStatusEnum.CREATED,
    )
    db.add(r); await db.flush(); return r


async def _make_offer(db: AsyncSession, request_id: UUID, service_id: UUID) -> Offer:
    o = Offer(
        request_id=request_id, service_id=service_id,
        price=Decimal("4500.00"), comment="Тест", status=OfferStatusEnum.SENT,
    )
    db.add(o); await db.flush(); return o


# ══════════════════════════════════════════════════════════════════════════════
# Unit: _send_notification
# ══════════════════════════════════════════════════════════════════════════════

class TestSendNotification:

    async def test_send_success(self) -> None:
        """200 от бота → без исключений."""
        mock_resp = MagicMock(); mock_resp.status_code = 200
        mock_cli = AsyncMock()
        mock_cli.__aenter__ = AsyncMock(return_value=mock_cli)
        mock_cli.__aexit__ = AsyncMock(return_value=False)
        mock_cli.post = AsyncMock(return_value=mock_resp)
        with patch("api.services.notifications.httpx.AsyncClient", return_value=mock_cli):
            await _send_notification(12345, "Тест")
        mock_cli.post.assert_called_once()
        kw = mock_cli.post.call_args[1]
        assert kw["json"]["telegram_id"] == 12345
        assert kw["json"]["text"] == "Тест"

    async def test_text_truncated_to_4000_chars(self) -> None:
        """Текст >4000 символов обрезается до 4000 перед отправкой (Telegram limit)."""
        mock_resp = MagicMock(); mock_resp.status_code = 200
        mock_cli = AsyncMock()
        mock_cli.__aenter__ = AsyncMock(return_value=mock_cli)
        mock_cli.__aexit__ = AsyncMock(return_value=False)
        mock_cli.post = AsyncMock(return_value=mock_resp)
        with patch("api.services.notifications.httpx.AsyncClient", return_value=mock_cli):
            await _send_notification(1, "А" * 5000)
        sent = mock_cli.post.call_args[1]["json"]["text"]
        assert len(sent) == 4000

    async def test_bot_500_no_exception(self) -> None:
        """Бот вернул 500 → функция не бросает."""
        mock_resp = MagicMock(); mock_resp.status_code = 500; mock_resp.text = "err"
        mock_cli = AsyncMock()
        mock_cli.__aenter__ = AsyncMock(return_value=mock_cli)
        mock_cli.__aexit__ = AsyncMock(return_value=False)
        mock_cli.post = AsyncMock(return_value=mock_resp)
        with patch("api.services.notifications.httpx.AsyncClient", return_value=mock_cli):
            await _send_notification(1, "test")  # не бросает

    async def test_network_error_no_exception(self) -> None:
        """Сеть недоступна → не бросает."""
        import httpx as _httpx
        mock_cli = AsyncMock()
        mock_cli.__aenter__ = AsyncMock(return_value=mock_cli)
        mock_cli.__aexit__ = AsyncMock(return_value=False)
        mock_cli.post = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        with patch("api.services.notifications.httpx.AsyncClient", return_value=mock_cli):
            await _send_notification(1, "test")  # не бросает


# ══════════════════════════════════════════════════════════════════════════════
# Unit: notify_services_new_request (UUID-based)
# ══════════════════════════════════════════════════════════════════════════════

class TestNotifyServicesNewRequest:

    async def test_notifies_matching_service(self, db_session: AsyncSession) -> None:
        """Сервис с area=Центр получает уведомление о заявке area=Центр."""
        user = await create_user(db_session, 500001, RoleEnum.USER)
        _, sp_center = await _make_service(db_session, 500002, ["Центр", "Север"])
        _, sp_south = await _make_service(db_session, 500003, ["Юг"])
        req = await _make_request(db_session, user.id, area="Центр")

        sent: list[int] = []
        async def mock_send(tid: int, text: str) -> None: sent.append(tid)

        with patch("api.services.notifications._send_notification", side_effect=mock_send):
            await notify_services_new_request(
                db_session, request_id=req.id, area=req.area,
                car_brand=req.car_brand, car_model=req.car_model, car_year=req.car_year,
                description=req.description, preferred_date=req.preferred_date,
                preferred_time=req.preferred_time,
            )
        assert 500002 in sent
        assert 500003 not in sent

    async def test_no_matching_services_no_send(self, db_session: AsyncSession) -> None:
        """Нет сервисов в area → _send_notification не вызывается."""
        user = await create_user(db_session, 501001, RoleEnum.USER)
        req = await _make_request(db_session, user.id, area="Восток")

        with patch("api.services.notifications._send_notification", new_callable=AsyncMock) as m:
            await notify_services_new_request(
                db_session, request_id=req.id, area=req.area,
                car_brand=req.car_brand, car_model=req.car_model, car_year=req.car_year,
                description=req.description, preferred_date=req.preferred_date,
                preferred_time=req.preferred_time,
            )
            m.assert_not_called()

    async def test_inactive_service_excluded(self, db_session: AsyncSession) -> None:
        """Неактивный сервис не получает уведомлений."""
        user = await create_user(db_session, 502001, RoleEnum.USER)
        svc = await create_user(db_session, 502002, RoleEnum.SERVICE)
        db_session.add(ServiceProfile(
            user_id=svc.id, name="Неактивный", areas=["Центр"],
            services=["ТО"], phone="+79001112233", is_active=False,
        ))
        await db_session.flush()
        req = await _make_request(db_session, user.id, area="Центр")

        with patch("api.services.notifications._send_notification", new_callable=AsyncMock) as m:
            await notify_services_new_request(
                db_session, request_id=req.id, area=req.area,
                car_brand=req.car_brand, car_model=req.car_model, car_year=req.car_year,
                description=req.description, preferred_date=req.preferred_date,
                preferred_time=req.preferred_time,
            )
            m.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Unit: notify_user_new_offer (UUID-based)
# ══════════════════════════════════════════════════════════════════════════════

class TestNotifyUserNewOffer:

    async def test_notifies_request_owner(self, db_session: AsyncSession) -> None:
        """Владелец заявки получает уведомление с ценой."""
        user = await create_user(db_session, 503001, RoleEnum.USER)
        _, sp = await _make_service(db_session, 503002, ["Центр"])
        req = await _make_request(db_session, user.id)
        offer = await _make_offer(db_session, req.id, sp.id)

        sent: list[int] = []; texts: list[str] = []
        async def mock_send(tid: int, text: str) -> None:
            sent.append(tid); texts.append(text)

        with patch("api.services.notifications._send_notification", side_effect=mock_send):
            await notify_user_new_offer(db_session, offer_id=offer.id)

        assert sent == [503001]
        assert "4" in texts[0]  # 4500 ₽

    async def test_includes_service_name(self, db_session: AsyncSession) -> None:
        """Текст уведомления содержит название сервиса."""
        user = await create_user(db_session, 504001, RoleEnum.USER)
        _, sp = await _make_service(db_session, 504002, ["Центр"])
        req = await _make_request(db_session, user.id)
        offer = await _make_offer(db_session, req.id, sp.id)

        texts: list[str] = []
        async def mock_send(tid: int, text: str) -> None: texts.append(text)

        with patch("api.services.notifications._send_notification", side_effect=mock_send):
            await notify_user_new_offer(db_session, offer_id=offer.id)
        assert sp.name in texts[0]

    async def test_unknown_offer_id_no_exception(self, db_session: AsyncSession) -> None:
        """Несуществующий offer_id → не бросает, не отправляет."""
        with patch("api.services.notifications._send_notification", new_callable=AsyncMock) as m:
            await notify_user_new_offer(db_session, offer_id=uuid4())
            m.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Unit: notify_service_offer_selected (UUID-based)
# ══════════════════════════════════════════════════════════════════════════════

class TestNotifyServiceOfferSelected:

    async def test_notifies_winning_service(self, db_session: AsyncSession) -> None:
        """Сервис-победитель получает уведомление."""
        user = await create_user(db_session, 506001, RoleEnum.USER)
        svc_user, sp = await _make_service(db_session, 506002, ["Центр"])
        req = await _make_request(db_session, user.id)
        offer = await _make_offer(db_session, req.id, sp.id)

        sent: list[int] = []
        async def mock_send(tid: int, text: str) -> None: sent.append(tid)

        with patch("api.services.notifications._send_notification", side_effect=mock_send):
            await notify_service_offer_selected(db_session, offer_id=offer.id)
        assert sent == [506002]

    async def test_unknown_offer_id_no_exception(self, db_session: AsyncSession) -> None:
        """Несуществующий offer_id → не бросает."""
        with patch("api.services.notifications._send_notification", new_callable=AsyncMock) as m:
            await notify_service_offer_selected(db_session, offer_id=uuid4())
            m.assert_not_called()


# ══════════════════════════════════════════════════════════════════════════════
# Интеграция: ошибка уведомления не блокирует основную операцию
# ══════════════════════════════════════════════════════════════════════════════

class TestBackgroundTaskIsolation:

    async def test_create_request_201_even_if_notify_fails(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """POST /requests/ → 201 даже при падении уведомления."""
        user = await create_user(db_session, 601001, RoleEnum.USER)
        with patch("api.routers.requests.AsyncSessionFactory", side_effect=Exception("DB down")):
            resp = await client.post(
                "/api/v1/requests/", json=REQUEST_BODY, headers=auth(user.telegram_id)
            )
        assert resp.status_code == 201

    async def test_create_offer_201_even_if_notify_fails(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """POST /offers/ → 201 даже при падении уведомления."""
        user = await create_user(db_session, 602001, RoleEnum.USER)
        _, sp = await _make_service(db_session, 602002, ["Центр"])
        req = await _make_request(db_session, user.id)
        with patch("api.routers.offers.AsyncSessionFactory", side_effect=Exception("DB down")):
            resp = await client.post(
                "/api/v1/offers/",
                json={**OFFER_BODY, "request_id": str(req.id)},
                headers=auth(sp.user_id),
            )
        assert resp.status_code == 201

    async def test_select_offer_200_even_if_notify_fails(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """PATCH /offers/{id}/select → 200 даже при падении уведомления."""
        user = await create_user(db_session, 603001, RoleEnum.USER)
        _, sp = await _make_service(db_session, 603002, ["Центр"])
        req = await _make_request(db_session, user.id)
        offer = await _make_offer(db_session, req.id, sp.id)
        with patch("api.routers.offers.AsyncSessionFactory", side_effect=Exception("DB down")):
            resp = await client.patch(
                f"/api/v1/offers/{offer.id}/select",
                json={"confirm": True},
                headers=auth(user.telegram_id),
            )
        assert resp.status_code == 200
