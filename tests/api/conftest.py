"""
tests/api/conftest.py
──────────────────────
Общие фикстуры для тестов API.

Стратегия:
  - SQLite in-memory через aiosqlite — быстро, без Docker
  - Один engine на сессию pytest (таблицы создаются один раз)
  - Каждый тест получает изолированную транзакцию → rollback после теста
  - Dependency override get_db — тесты используют ту же сессию что и приложение
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.dependencies.db import get_db
from api.main import create_app
from common.models.base import Base
from common.models.enums import RoleEnum
from common.models.user import User

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Один engine на всю сессию pytest. Таблицы создаются один раз."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        # SQLite: отключаем проверку потоков — нужно для async
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(test_engine) -> AsyncSession:
    """
    Изолированная сессия на каждый тест.

    Используем savepoint (nested transaction) — тест может делать flush/commit,
    но внешняя транзакция всё равно откатится. Это обеспечивает изоляцию
    между тестами без пересоздания таблиц.
    """
    factory = async_sessionmaker(test_engine, expire_on_commit=False)
    async with factory() as session:
        await session.begin_nested()   # savepoint
        yield session
        await session.rollback()       # откат savepoint → тест изолирован


@pytest_asyncio.fixture()
async def client(db_session: AsyncSession) -> AsyncClient:
    """
    AsyncClient с подменённой зависимостью get_db.
    Все запросы через этот клиент используют db_session теста.
    """
    app = create_app()

    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


# ── Helpers ───────────────────────────────────────────────────────────────────

async def create_user(
    db: AsyncSession,
    telegram_id: int,
    role: RoleEnum,
) -> User:
    """Вспомогательная функция: создать пользователя напрямую в БД."""
    user = User(telegram_id=telegram_id, role=role)
    db.add(user)
    await db.flush()
    return user


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture()
async def user_regular(db_session: AsyncSession) -> User:
    """Пользователь с ролью USER (telegram_id=111111)."""
    return await create_user(db_session, telegram_id=111_111, role=RoleEnum.USER)


@pytest_asyncio.fixture()
async def user_service(db_session: AsyncSession) -> User:
    """Пользователь с ролью SERVICE (telegram_id=222222)."""
    return await create_user(db_session, telegram_id=222_222, role=RoleEnum.SERVICE)


@pytest_asyncio.fixture()
async def user_admin(db_session: AsyncSession) -> User:
    """Пользователь с ролью ADMIN (telegram_id=333333)."""
    return await create_user(db_session, telegram_id=333_333, role=RoleEnum.ADMIN)

