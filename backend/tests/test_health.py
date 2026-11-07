import pytest
from httpx import ASGITransport, AsyncClient

from app.db import get_session
from app.main import app


@pytest.mark.asyncio
async def test_health_returns_ok_with_db_connected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "ok", "db": "ok"}


@pytest.mark.asyncio
async def test_health_reports_degraded_when_the_db_query_fails():
    class _BrokenSession:
        async def execute(self, *args, **kwargs):
            raise RuntimeError("connection refused")

    async def _broken_get_session():
        yield _BrokenSession()

    app.dependency_overrides[get_session] = _broken_get_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    assert response.json() == {"status": "degraded", "db": "error"}
