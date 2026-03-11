"""
api/services/admin.py
──────────────────────
Бизнес-логика для административного API.

Принцип: сервис не знает о HTTP. Получает данные — возвращает результат
или бросает AppError. Все функции принимают db: AsyncSession.

Функции:
    get_admin_requests  — список всех заявок с фильтрацией + offers_count
    get_admin_users     — список пользователей с пагинацией
    block_user          — заблокировать / разблокировать пользователя
    get_stats           — агрегированные метрики платформы
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.exceptions import ForbiddenError, NotFoundError
from api.services.common import RequestWithOffersCount
from common.models.car_request import CarRequest
from common.models.enums import RequestStatusEnum, RoleEnum
from common.models.offer import Offer
from common.models.service_profile import ServiceProfile
from common.models.user import User

logger = logging.getLogger(__name__)

# Максимальный и дефолтный размер страницы для /admin/users
USERS_PAGE_SIZE_MAX = 100
USERS_PAGE_SIZE_DEFAULT = 20



@dataclass(frozen=True, slots=True)
class StatsResult:
    """Агрегированные метрики платформы."""
    total_requests: int
    total_users: int
    total_services: int
    conversion_rate: float
    avg_offers_per_request: float
    requests_by_status: dict[str, int]


async def get_admin_requests(
    db: AsyncSession,
    *,
    status: RequestStatusEnum | None = None,
    area: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> list[RequestWithOffersCount]:
    """
    Список всех заявок с фильтрацией и пагинацией.

    Args:
        db:        AsyncSession
        status:    Фильтр по статусу (None = все)
        area:      Фильтр по району (None = все)
        page:      Страница (с 1)
        page_size: Размер страницы (макс 200)

    Returns:
        list[RequestWithOffersCount]
    """
    page_size = min(max(page_size, 1), 200)
    offset = (max(page, 1) - 1) * page_size
    offers_subq = (
        select(
            Offer.request_id,
            func.count(Offer.id).label("offers_count"),
        )
        .group_by(Offer.request_id)
        .subquery()
    )

    stmt = (
        select(
            CarRequest,
            func.coalesce(offers_subq.c.offers_count, 0).label("offers_count"),
        )
        .outerjoin(offers_subq, CarRequest.id == offers_subq.c.request_id)
        .order_by(CarRequest.created_at.desc())
        .limit(page_size)
        .offset(offset)
    )

    if status is not None:
        stmt = stmt.where(CarRequest.status == status)

    if area is not None:
        stmt = stmt.where(CarRequest.area == area)

    rows = (await db.execute(stmt)).all()
    return [
        RequestWithOffersCount(request=row.CarRequest, offers_count=row.offers_count)
        for row in rows
    ]


async def get_admin_users(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = USERS_PAGE_SIZE_DEFAULT,
) -> tuple[list[User], int]:
    """
    Список пользователей с пагинацией (offset-based).

    Args:
        db:        AsyncSession
        page:      Номер страницы (с 1)
        page_size: Размер страницы (1–USERS_PAGE_SIZE_MAX)

    Returns:
        Tuple[list[User], total_count]
    """
    page_size = min(max(page_size, 1), USERS_PAGE_SIZE_MAX)
    offset = (max(page, 1) - 1) * page_size

    # Общее количество (для мета-информации) и список — одним запросом через subquery
    count_stmt = select(func.count(User.id))
    total: int = (await db.execute(count_stmt)).scalar_one()

    users_stmt = (
        select(User)
        .order_by(User.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    users = list((await db.execute(users_stmt)).scalars().all())

    return users, total


async def block_user(
    db: AsyncSession,
    *,
    target_user_id: UUID,
    admin_user_id: UUID,
    block: bool,
) -> User:
    """
    Заблокировать или разблокировать пользователя.

    Нельзя заблокировать самого себя и другого администратора.

    Args:
        db:             AsyncSession
        target_user_id: UUID блокируемого пользователя
        admin_user_id:  UUID администратора (для проверки self-block)
        block:          True = заблокировать, False = разблокировать

    Returns:
        Обновлённый User

    Raises:
        NotFoundError:  если пользователь не найден (404)
        ForbiddenError: если попытка заблокировать себя или другого admin (403)
    """
    result = await db.execute(select(User).where(User.id == target_user_id))
    target = result.scalar_one_or_none()

    if target is None:
        raise NotFoundError(f"User {target_user_id} not found")

    if target.id == admin_user_id:
        raise ForbiddenError("Cannot block yourself")

    if target.role == RoleEnum.ADMIN:
        raise ForbiddenError("Cannot block another admin")

    target.is_blocked = block
    await db.flush()

    action = "blocked" if block else "unblocked"
    logger.info(
        "admin: user %s %s by admin %s",
        target_user_id, action, admin_user_id,
    )
    return target


async def get_stats(db: AsyncSession) -> StatsResult:
    """
    Агрегированные метрики платформы.

    Метрики:
        total_requests         — общее число заявок
        total_users            — пользователи с role=USER
        total_services         — пользователи с role=SERVICE
        conversion_rate        — доля заявок с ≥1 оффером
        avg_offers_per_request — среднее офферов (по заявкам с офферами)
        requests_by_status     — количество заявок по каждому статусу

    Все метрики вычисляются за один проход по БД (4 запроса).
    """
    # 1. Общее число заявок
    total_requests: int = (
        await db.execute(select(func.count(CarRequest.id)))
    ).scalar_one()

    # 2. Число пользователей по ролям
    role_counts = (
        await db.execute(
            select(User.role, func.count(User.id).label("cnt"))
            .group_by(User.role)
        )
    ).all()
    role_map = {row.role: row.cnt for row in role_counts}
    total_users: int = role_map.get(RoleEnum.USER, 0)
    total_services: int = role_map.get(RoleEnum.SERVICE, 0)

    # 3. Заявки по статусам
    status_counts = (
        await db.execute(
            select(CarRequest.status, func.count(CarRequest.id).label("cnt"))
            .group_by(CarRequest.status)
        )
    ).all()
    requests_by_status: dict[str, int] = {
        row.status.value: row.cnt for row in status_counts
    }
    # Гарантируем наличие всех статусов (с нулями)
    for s in RequestStatusEnum:
        requests_by_status.setdefault(s.value, 0)

    # 4. Конверсия и средний offers_count
    # Запрос: число заявок с ≥1 оффером и суммарное число офферов
    offers_agg = (
        await db.execute(
            select(
                func.count(func.distinct(Offer.request_id)).label("requests_with_offers"),
                func.count(Offer.id).label("total_offers"),
            )
        )
    ).one()

    requests_with_offers: int = offers_agg.requests_with_offers or 0
    total_offers: int = offers_agg.total_offers or 0

    conversion_rate = (
        requests_with_offers / total_requests if total_requests > 0 else 0.0
    )
    avg_offers_per_request = (
        total_offers / requests_with_offers if requests_with_offers > 0 else 0.0
    )

    return StatsResult(
        total_requests=total_requests,
        total_users=total_users,
        total_services=total_services,
        conversion_rate=round(conversion_rate, 4),
        avg_offers_per_request=round(avg_offers_per_request, 2),
        requests_by_status=requests_by_status,
    )
