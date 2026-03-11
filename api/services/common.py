"""
api/services/common.py
───────────────────────
Общие dataclass-ы, переиспользуемые в нескольких сервисах.
Вынесены сюда, чтобы избежать дублирования между requests.py и admin.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from common.models.car_request import CarRequest


@dataclass(frozen=True, slots=True)
class RequestWithOffersCount:
    """CarRequest + денормализованный offers_count."""
    request: CarRequest
    offers_count: int
