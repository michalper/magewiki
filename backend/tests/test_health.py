import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routes import health as health_module
from app.db import get_session
from app.main import app


@pytest.mark.asyncio
async def test_health_returns_ok_with_db_connected_and_schema_current():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["schema"] == "ok"
    # The real dev/test DB is migrated to head by conftest.py, so this is a
    # genuine equality check, not a tautology against the same mocked value.
    assert body["db_revision"] == body["code_revision"] == health_module._CODE_REVISION


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
    assert response.json() == {
        "status": "degraded",
        "db": "error",
        "schema": "unknown",
        "db_revision": None,
        "code_revision": health_module._CODE_REVISION,
    }


@pytest.mark.asyncio
async def test_health_reports_stale_schema_when_db_revision_differs_from_code():
    class _StaleSession:
        async def execute(self, clause, *args, **kwargs):
            class _Result:
                def scalar_one_or_none(self_inner):
                    return "some-old-revision"

            return _Result()

    async def _stale_get_session():
        yield _StaleSession()

    app.dependency_overrides[get_session] = _stale_get_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "ok"
    assert body["schema"] == "stale"
    assert body["db_revision"] == "some-old-revision"


@pytest.mark.asyncio
async def test_health_reports_stale_schema_when_alembic_version_table_is_missing():
    class _NoVersionTableSession:
        async def execute(self, clause, *args, **kwargs):
            if "alembic_version" in str(clause):
                raise RuntimeError('relation "alembic_version" does not exist')

    async def _no_version_table_get_session():
        yield _NoVersionTableSession()

    app.dependency_overrides[get_session] = _no_version_table_get_session
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["db"] == "ok"
    assert body["schema"] == "stale"
    assert body["db_revision"] is None
