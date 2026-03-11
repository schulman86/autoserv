"""
models/enums.py
───────────────
Все ENUM-типы проекта.

Принцип: Python-enum дублирует PostgreSQL ENUM.
При миграции Alembic создаёт pg-типы через sa.Enum(PyEnum).
"""

import enum


class RoleEnum(str, enum.Enum):
    """
    Роль пользователя в системе.

    Значения используются в:
      - users.role
      - POST /auth/telegram → role field
      - RBAC middleware
    """

    USER = "user"
    SERVICE = "service"
    ADMIN = "admin"


class RequestStatusEnum(str, enum.Enum):
    """
    Статус жизненного цикла заявки на ремонт.

    Диаграмма переходов:
        created
           ├─→ offers       (получен ≥1 оффер)
           └─→ cancelled    (пользователь отменил)
        offers
           ├─→ selected     (пользователь выбрал оффер)
           └─→ cancelled
        selected
           └─→ done         (визит состоялся)
        done       — terminal
        cancelled  — terminal
    """

    CREATED = "created"
    OFFERS = "offers"
    SELECTED = "selected"
    DONE = "done"
    CANCELLED = "cancelled"

    # Терминальные состояния (не переходят в другие)
    @classmethod
    def terminal_states(cls) -> set["RequestStatusEnum"]:
        return {cls.DONE, cls.CANCELLED}


class OfferStatusEnum(str, enum.Enum):
    """
    Статус коммерческого предложения от автосервиса.

    Диаграмма переходов:
        sent
         ├─→ selected    (пользователь выбрал этот оффер)
         └─→ rejected    (пользователь выбрал другой оффер,
                          система обновляет автоматически)
        selected  — terminal
        rejected  — terminal
    """

    SENT = "sent"
    SELECTED = "selected"
    REJECTED = "rejected"

    @classmethod
    def terminal_states(cls) -> set["OfferStatusEnum"]:
        return {cls.SELECTED, cls.REJECTED}
