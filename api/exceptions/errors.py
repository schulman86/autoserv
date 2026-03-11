"""
api/exceptions/errors.py
─────────────────────────
Типизированные исключения приложения.

Принцип: каждый бизнес-кейс → отдельное исключение.
HTTP-статус и error_code прописаны в самом классе,
не разбросаны по роутерам.

Обработчики зарегистрированы в api/main.py через add_exception_handler.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AppError(Exception):
    """
    Базовое типизированное исключение.
    Все бизнес-ошибки наследуют отсюда.
    """
    message: str
    http_status: int = field(default=500, repr=False)
    error_code: str = field(default="INTERNAL_ERROR", repr=False)

    def __str__(self) -> str:
        return self.message


# ── 401 ──────────────────────────────────────────────────────────────────────

@dataclass
class UnauthorizedError(AppError):
    """Telegram ID не найден / не передан."""
    message: str = "Unauthorized"
    http_status: int = field(default=401, repr=False)
    error_code: str = field(default="UNAUTHORIZED", repr=False)


# ── 403 ──────────────────────────────────────────────────────────────────────

@dataclass
class ForbiddenError(AppError):
    """Недостаточно прав (роль не соответствует)."""
    message: str = "Forbidden"
    http_status: int = field(default=403, repr=False)
    error_code: str = field(default="FORBIDDEN", repr=False)


# ── 404 ──────────────────────────────────────────────────────────────────────

@dataclass
class NotFoundError(AppError):
    """Запрошенный ресурс не существует."""
    message: str = "Not found"
    http_status: int = field(default=404, repr=False)
    error_code: str = field(default="NOT_FOUND", repr=False)


# ── 409 ──────────────────────────────────────────────────────────────────────

@dataclass
class AlreadySelectedError(AppError):
    """Попытка выбрать оффер, когда уже выбран другой."""
    message: str = "Offer already selected"
    http_status: int = field(default=409, repr=False)
    error_code: str = field(default="ALREADY_SELECTED", repr=False)


@dataclass
class ConflictError(AppError):
    """Нарушение уникальности (напр. повторный оффер от того же сервиса)."""
    message: str = "Conflict"
    http_status: int = field(default=409, repr=False)
    error_code: str = field(default="CONFLICT", repr=False)


# ── 422 ──────────────────────────────────────────────────────────────────────

@dataclass
class InvalidStatusError(AppError):
    """Действие недоступно при текущем статусе заявки/оффера."""
    message: str = "Action not allowed for current status"
    http_status: int = field(default=422, repr=False)
    error_code: str = field(default="INVALID_STATUS", repr=False)


# ── 429 ──────────────────────────────────────────────────────────────────────

@dataclass
class RateLimitError(AppError):
    """Превышен лимит запросов."""
    message: str = "Too many requests"
    http_status: int = field(default=429, repr=False)
    error_code: str = field(default="RATE_LIMIT", repr=False)
