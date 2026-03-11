"""
api/main.py
────────────
FastAPI application factory.

Запуск:
    uvicorn api.main:app --reload --port 8000

Структура:
    /api/v1/...  — все бизнес-эндпоинты (версионированные)
    /healthz     — liveness probe (без аутентификации, без версии)
"""

from __future__ import annotations

import logging
import logging.config
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.exceptions import AppError
from api.middlewares import RequestLoggingMiddleware, TelegramAuthMiddleware
from common.config import settings
from common.models.database import Base, engine

from api.routers import auth as auth_router
from api.routers import offers as offers_router
from api.routers import requests as requests_router
from api.routers import service_profile as service_profile_router
from api.routers import admin as admin_router

logger = logging.getLogger(__name__)


# ── Logging setup ─────────────────────────────────────────────────────────────

def _configure_logging() -> None:
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "datefmt": "%Y-%m-%dT%H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
            },
        },
        "root": {
            "level": "DEBUG" if not settings.is_production else "INFO",
            "handlers": ["console"],
        },
        "loggers": {
            # Подавляем шум от sqlalchemy в dev (включить echo=True в engine для SQL)
            "sqlalchemy.engine": {"level": "WARNING"},
            "sqlalchemy.pool": {"level": "WARNING"},
            # Aiogram внутри api не используется, но на случай
            "aiogram": {"level": "WARNING"},
        },
    })


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    _configure_logging()
    logger.info("Starting API (env=%s)", settings.app_env)

    if not settings.is_production:
        # Dev/test: create_all для быстрого старта без Alembic
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.debug("Tables ensured via create_all (non-production)")

    yield

    await engine.dispose()
    logger.info("API shutdown complete")


# ── Exception handlers ────────────────────────────────────────────────────────

def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    """Единая обработка всех AppError → структурированный JSON."""
    return JSONResponse(
        status_code=exc.http_status,
        content={"error_code": exc.error_code, "detail": exc.message},
    )


def _unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """Fallback для необработанных исключений — скрываем детали от клиента."""
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error_code": "INTERNAL_ERROR", "detail": "Internal server error"},
    )


# ── Factory ───────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="AutoService API",
        description=(
            "Backend API для SaaS-платформы автосервисов.\n\n"
            "**Аутентификация**: заголовок `X-Telegram-ID: <telegram_user_id>`\n\n"
            "**Базовый путь**: `/api/v1`"
        ),
        version="1.0.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── Middleware (порядок важен: первый зарегистрированный = последний в цепочке) ──
    # Logging → Auth → handler
    app.add_middleware(TelegramAuthMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.api_base_url],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception handlers ────────────────────────────────────────────────────
    app.add_exception_handler(AppError, _app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_error_handler)

    # ── Versioned API router ──────────────────────────────────────────────────
    # Все бизнес-роутеры монтируются под /api/v1
    app.include_router(auth_router.router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(requests_router.router, prefix="/api/v1/requests", tags=["requests"])
    app.include_router(offers_router.router, prefix="/api/v1/offers", tags=["offers"])
    app.include_router(service_profile_router.router, prefix="/api/v1/service-profile", tags=["service-profile"])
    app.include_router(admin_router.router, prefix="/api/v1/admin", tags=["admin"])

    # ── Infrastructure endpoints ──────────────────────────────────────────────

    @app.get("/healthz", tags=["infra"], include_in_schema=False)
    async def health_check():  # type: ignore[return]
        """Liveness + readiness probe — проверяет доступность БД."""
        from sqlalchemy import text as _text
        from fastapi.responses import JSONResponse
        try:
            async with engine.connect() as conn:
                await conn.execute(_text("SELECT 1"))
        except Exception as exc:
            logger.error("healthz: DB unavailable: %s", exc)
            return JSONResponse(
                status_code=503,
                content={"status": "error", "detail": "database unavailable"},
            )
        return {"status": "ok"}

    return app


app = create_app()

