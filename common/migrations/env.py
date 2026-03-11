"""
migrations/env.py
──────────────────
Alembic миграционная среда (async режим).

Шаги настройки:
    1. alembic init -t async migrations
    2. Заменить migrations/env.py этим файлом
    3. В alembic.ini установить:
         sqlalchemy.url = postgresql+asyncpg://...
       Или использовать DATABASE_URL из окружения (см. ниже)

Создание первой миграции:
    alembic revision --autogenerate -m "initial schema"

Применение:
    alembic upgrade head

Откат:
    alembic downgrade -1
"""

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Импортируем Base и ВСЕ модели, чтобы metadata был полным
from models.base import Base
from models import User, ServiceProfile, CarRequest, Offer  # noqa: F401

# ── Alembic Config ────────────────────────────────────────────────────────────

config = context.config

# Переопределяем URL из env-переменной (приоритет перед alembic.ini)
database_url = os.environ.get("DATABASE_URL")
if database_url:
    # asyncpg нужен для async engine, psycopg2/psycopg для sync
    config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Метаданные для autogenerate
target_metadata = Base.metadata


# ── Offline mode (генерация SQL без подключения) ──────────────────────────────

def run_migrations_offline() -> None:
    """
    Генерирует SQL-скрипт миграции без подключения к БД.
    Полезно для проверки и ревью перед применением.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,          # Сравнивать типы столбцов
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode (применение к реальной БД) ────────────────────────────────────

def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


# ── Точка входа ───────────────────────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
