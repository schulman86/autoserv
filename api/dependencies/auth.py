"""
api/dependencies/auth.py
─────────────────────────
FastAPI dependencies для аутентификации и авторизации.

Использование в роутерах:

    # Любой аутентифицированный пользователь
    @router.get("/requests/my")
    async def my_requests(user: CurrentUser) -> ...:
        ...

    # Только роль USER
    @router.post("/requests")
    async def create_request(user: CurrentUser, _: UserOnly) -> ...:
        ...

    # Только роль SERVICE
    @router.post("/offers")
    async def create_offer(user: CurrentUser, _: ServiceOnly) -> ...:
        ...

    # Только ADMIN
    @router.get("/admin/requests")
    async def admin_requests(user: CurrentUser, _: AdminOnly) -> ...:
        ...
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.db import get_db
from api.exceptions import ForbiddenError, UnauthorizedError
from common.models.enums import RoleEnum
from common.models.user import User


async def current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Загружает User из БД по telegram_id из request.state.
    state.telegram_id устанавливается TelegramAuthMiddleware.

    Raises:
        UnauthorizedError: если telegram_id отсутствует в state
                           или пользователь не найден в БД
    """
    telegram_id: int | None = getattr(request.state, "telegram_id", None)
    if telegram_id is None:
        # Не должно случиться если middleware настроен, но на случай тестов
        raise UnauthorizedError("Missing telegram_id in request state")

    result = await db.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise UnauthorizedError(
            f"User with telegram_id={telegram_id} not found. "
            "Please call POST /auth/telegram first."
        )

    if user.is_blocked:
        raise UnauthorizedError("Your account has been blocked. Contact support.")

    return user


# Annotated alias — использовать в сигнатурах роутеров
CurrentUser = Annotated[User, Depends(current_user)]


def _role_guard(*allowed_roles: RoleEnum):
    """
    Фабрика dependency: проверяет, что роль пользователя входит в allowed_roles.
    Возвращает dependency-функцию, которую можно использовать через Depends.
    """
    async def guard(user: User = Depends(current_user)) -> User:
        if user.role not in allowed_roles:
            raise ForbiddenError(
                f"Role '{user.role.value}' is not allowed. "
                f"Required: {', '.join(r.value for r in allowed_roles)}"
            )
        return user

    # Для корректного отображения в OpenAPI
    guard.__name__ = f"require_{'_or_'.join(r.value for r in allowed_roles)}"
    return guard


# ── Готовые guards для использования в роутерах ───────────────────────────────

# Depends(UserOnly) — только role=user
UserOnly = Annotated[User, Depends(_role_guard(RoleEnum.USER))]

# Depends(ServiceOnly) — только role=service
ServiceOnly = Annotated[User, Depends(_role_guard(RoleEnum.SERVICE))]

# Depends(AdminOnly) — только role=admin
AdminOnly = Annotated[User, Depends(_role_guard(RoleEnum.ADMIN))]

# Depends(UserOrAdmin) — user или admin (для просмотра своих заявок + admin)
UserOrAdmin = Annotated[User, Depends(_role_guard(RoleEnum.USER, RoleEnum.ADMIN))]
