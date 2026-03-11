"""
tests/api/test_schemas.py
──────────────────────────
Unit-тесты валидации схем.
Запускаются без БД и HTTP — чистая логика Pydantic.
"""

from __future__ import annotations

import datetime

import pytest
from pydantic import ValidationError

from api.schemas.auth import AuthTelegramRequest
from api.schemas.offer import OfferCreate
from api.schemas.request import CarRequestCreate
from api.schemas.service_profile import ServiceProfileUpsert


# ── AuthTelegramRequest ───────────────────────────────────────────────────────

class TestAuthTelegramRequest:
    def test_valid_user(self) -> None:
        req = AuthTelegramRequest(telegram_id=123, role="user")
        assert req.telegram_id == 123

    def test_valid_service(self) -> None:
        req = AuthTelegramRequest(telegram_id=456, role="service")
        assert req.role.value == "service"

    def test_admin_role_rejected(self) -> None:
        with pytest.raises(ValidationError, match="admin"):
            AuthTelegramRequest(telegram_id=1, role="admin")

    def test_zero_telegram_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AuthTelegramRequest(telegram_id=0, role="user")

    def test_negative_telegram_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AuthTelegramRequest(telegram_id=-1, role="user")


# ── CarRequestCreate ──────────────────────────────────────────────────────────

class TestCarRequestCreate:
    def _valid(self, **overrides: object) -> dict:
        return {
            "car_brand": "Toyota",
            "car_model": "Camry",
            "car_year": 2018,
            "description": "Замена тормозных колодок, скрип",
            "preferred_date": datetime.date.today() + datetime.timedelta(days=1),
            "preferred_time": datetime.time(12, 0),
            "area": "Центр",
            **overrides,
        }

    def test_valid(self) -> None:
        req = CarRequestCreate(**self._valid())
        assert req.car_brand == "Toyota"

    def test_past_date_rejected(self) -> None:
        with pytest.raises(ValidationError, match="past"):
            CarRequestCreate(**self._valid(preferred_date=datetime.date(2020, 1, 1)))

    def test_description_too_short(self) -> None:
        with pytest.raises(ValidationError):
            CarRequestCreate(**self._valid(description="кор"))

    def test_year_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            CarRequestCreate(**self._valid(car_year=1800))

    def test_year_too_large(self) -> None:
        with pytest.raises(ValidationError):
            CarRequestCreate(**self._valid(car_year=2100))


# ── OfferCreate ───────────────────────────────────────────────────────────────

class TestOfferCreate:
    def test_valid(self) -> None:
        import uuid
        offer = OfferCreate(request_id=uuid.uuid4(), price="4500.00")
        assert offer.price > 0

    def test_zero_price_rejected(self) -> None:
        import uuid
        with pytest.raises(ValidationError):
            OfferCreate(request_id=uuid.uuid4(), price="0")

    def test_negative_price_rejected(self) -> None:
        import uuid
        with pytest.raises(ValidationError):
            OfferCreate(request_id=uuid.uuid4(), price="-100")


# ── ServiceProfileUpsert ──────────────────────────────────────────────────────

class TestServiceProfileUpsert:
    def _valid(self, **overrides: object) -> dict:
        return {
            "name": "АвтоМастер",
            "areas": ["Центр"],
            "services": ["ТО", "Тормоза"],
            "phone": "+79990001122",
            **overrides,
        }

    def test_valid(self) -> None:
        profile = ServiceProfileUpsert(**self._valid())
        assert profile.name == "АвтоМастер"

    def test_invalid_phone_format(self) -> None:
        with pytest.raises(ValidationError):
            ServiceProfileUpsert(**self._valid(phone="89990001122"))

    def test_empty_areas_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ServiceProfileUpsert(**self._valid(areas=[]))

    def test_whitespace_only_area_filtered(self) -> None:
        with pytest.raises(ValidationError):
            ServiceProfileUpsert(**self._valid(areas=["   ", ""]))

    def test_areas_stripped(self) -> None:
        profile = ServiceProfileUpsert(**self._valid(areas=[" Центр ", " Юг"]))
        assert profile.areas == ["Центр", "Юг"]
