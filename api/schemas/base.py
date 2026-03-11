"""
api/schemas/base.py
────────────────────
Базовые Pydantic-схемы, переиспользуемые во всём API.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _Base(BaseModel):
    """Общие настройки для всех схем."""
    model_config = ConfigDict(
        from_attributes=True,   # ORM → schema без .model_validate вручную
        populate_by_name=True,
    )


class ErrorResponse(_Base):
    """Единый формат ошибок для всех эндпоинтов."""
    error_code: str
    detail: str


class TimestampedMixin(_Base):
    """Добавляет created_at в response-схемы."""
    id: UUID
    created_at: datetime
