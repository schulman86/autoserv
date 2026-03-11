"""
api/middlewares/auth.py
────────────────────────
Middleware аутентификации: читает X-Telegram-ID из заголовка,
загружает User из БД и кладёт в request.state.

Архитектурный принцип:
    Вся логика «кто делает запрос» живёт здесь — не в роутерах.
    Роутеры получают готовый объект User через Depends(current_user).

Поток:
    Request
      → TelegramAuthMiddleware (читает заголовок, пишет state.telegram_id)
      → Router handler
          → Depends(current_user) — lazy: загружает User из state.telegram_id
          → Depends(require_role(...)) — проверяет role

Публичные пути (OPEN_PATHS) не требуют аутентификации.
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# Пути, доступные без аутентификации
OPEN_PATHS: frozenset[str] = frozenset({
    "/healthz",
    "/docs",
    "/redoc",
    "/openapi.json",
    # Точка входа — telegram_id передаётся в body, не в заголовке
    "/api/v1/auth/telegram",
})

TELEGRAM_ID_HEADER = "X-Telegram-ID"


class TelegramAuthMiddleware(BaseHTTPMiddleware):
    """
    Читает заголовок X-Telegram-ID и сохраняет в request.state.telegram_id.

    Не загружает User из БД — это делает Depends(current_user) лениво,
    только когда нужно. Middleware только парсит и валидирует заголовок.

    Ответ 401 возвращается если:
      - Заголовок отсутствует на непубличном пути
      - Значение не является целым числом > 0
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Нормализуем путь: убираем /api/v1 префикс для сравнения
        path = request.url.path

        if self._is_open(path):
            return await call_next(request)

        raw = request.headers.get(TELEGRAM_ID_HEADER)
        if not raw:
            return _unauthorized("Missing X-Telegram-ID header")

        try:
            telegram_id = int(raw)
            if telegram_id <= 0:
                raise ValueError("non-positive")
        except ValueError:
            return _unauthorized("X-Telegram-ID must be a positive integer")

        request.state.telegram_id = telegram_id
        return await call_next(request)

    @staticmethod
    def _is_open(path: str) -> bool:
        # Точное совпадение или префикс для /docs, /redoc
        return path in OPEN_PATHS or any(
            path.startswith(p) for p in ("/docs", "/redoc", "/openapi")
        )


def _unauthorized(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"error_code": "UNAUTHORIZED", "detail": detail},
    )
