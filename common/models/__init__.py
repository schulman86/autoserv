"""
models/__init__.py
──────────────────
Публичный API пакета моделей.

Использование:
    from models import Base, User, ServiceProfile, CarRequest, Offer
    from models.enums import RoleEnum, RequestStatusEnum, OfferStatusEnum

Порядок импорта важен: Base должен быть импортирован первым,
чтобы все metadata были зарегистрированы до создания движка.
"""

from .base import Base
from .enums import OfferStatusEnum, RequestStatusEnum, RoleEnum
from .user import User
from .service_profile import ServiceProfile
from .car_request import CarRequest
from .offer import Offer

__all__ = [
    # Core
    "Base",
    # Models
    "User",
    "ServiceProfile",
    "CarRequest",
    "Offer",
    # Enums
    "RoleEnum",
    "RequestStatusEnum",
    "OfferStatusEnum",
]
