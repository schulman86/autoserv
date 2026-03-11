"""
models/database.py
──────────────────
Движок SQLAlchemy (async) и фабрика сессий.

Использование в FastAPI:

    # main.py
    from models.database import create_tables, engine

    @app.on_event("startup")
    async def startup():
        await create_tables()

    # В зависимостях FastAPI:
    from models.database import get_session

    @router.get("/requests")
    async def list_requests(session: AsyncSession = Depends(get_session)):
        ...

Переменные окружения:
    DATABASE_URL — строка подключения asyncpg
    Пример: postgresql+asyncpg://user:pass@localhost:5432/autoservice
"""

from __future__ import annotations


from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .base import Base
from common.config import settings

# ── Настройки ────────────────────────────────────────────────────────────────

DATABASE_URL: str = settings.database_url

# pool_pre_ping: проверять соединение перед использованием
# pool_size: начальный пул соединений для MVP
# max_overflow: дополнительные соединения сверх pool_size
engine = create_async_engine(
    DATABASE_URL,
    echo=False,           # True только для отладки (логирует все SQL)
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
)

# Фабрика сессий — переиспользуется во всём приложении
AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,   # Не сбрасывать атрибуты после commit (важно для async)
    autoflush=False,
    autocommit=False,
)


# ── Утилиты ──────────────────────────────────────────────────────────────────

async def create_tables() -> None:
    """
    Создать все таблицы по метаданным.
    Используется для разработки и тестов.
    В production — только через Alembic миграции.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables() -> None:
    """Удалить все таблицы. Только для тестов."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
