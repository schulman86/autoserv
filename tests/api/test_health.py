"""
tests/api/test_health.py
─────────────────────────
Smoke-тест: API стартует и отвечает на /healthz.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import create_app


@pytest.fixture()
def app():
    return create_app()


@pytest.mark.asyncio
async def test_healthz(app, monkeypatch):
    """GET /healthz → 200 OK."""
    # Не поднимаем реальную БД — патчим lifespan
    monkeypatch.setattr("api.main.settings.is_production", False)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # Обходим lifespan (create_all) — тестируем только роутинг
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
