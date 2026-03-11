"""
api/middlewares/logging.py
───────────────────────────
Structured request/response logging.
Логирует метод, путь, статус, время выполнения, telegram_id (если есть).
"""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("api.access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        telegram_id = getattr(request.state, "telegram_id", None)

        logger.info(
            "%s %s → %d (%.1fms)%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            f" tg={telegram_id}" if telegram_id else "",
        )
        return response
