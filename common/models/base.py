"""
models/base.py
──────────────
Базовый класс для всех SQLAlchemy-моделей.
Использует DeclarativeBase (SQLAlchemy 2.x) + MappedColumn API.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp helper."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """
    Базовый класс для всех ORM-моделей.

    Все таблицы наследуют:
      - id: UUID первичный ключ
      - created_at: TIMESTAMP WITH TZ, автозаполняется при INSERT
    """

    # Абстрактный — не создаёт собственную таблицу
    __abstract__ = True

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
        comment="Внутренний UUID-идентификатор записи",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Timestamp создания записи (UTC)",
    )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} id={self.id}>"
