"""
api/dependencies/db.py
───────────────────────
FastAPI dependency: AsyncSession per request.
Переносим из common/models/database.py для явного разделения слоёв.
"""

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from common.models.database import AsyncSessionFactory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Открывает сессию на время HTTP-запроса.
    При успехе — commit, при исключении — rollback.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Annotated alias для краткости в роутерах:
#   async def handler(db: DbSession) -> ...:
from typing import Annotated
DbSession = Annotated[AsyncSession, Depends(get_db)]
