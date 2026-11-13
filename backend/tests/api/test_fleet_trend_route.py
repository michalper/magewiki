import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.main import app
from app.models import Module, ModuleHistorySnapshot


async def _make_module(session, suffix: str) -> Module:
    module = Module(
        repo_root=f"/tmp/fleet-trend-route-test-{suffix}",
        name=f"Vendor_{suffix}",
        path=".",
        source_type="standalone",
        state="up_to_date",
        current_hash=f"hash-{suffix}",
        last_scanned_at=datetime.now(UTC),
    )
    session.add(module)
    await session.flush()
    return module


@pytest.mark.asyncio
async def test_fleet_trend_route_includes_a_real_point(db_session):
    suffix = uuid.uuid4().hex[:8]
    t0 = datetime.now(UTC) + timedelta(days=36501, microseconds=int(suffix, 16) % 1_000_000)
    module = await _make_module(db_session, suffix)
    db_session.add(
        ModuleHistorySnapshot(
            module_id=module.id,
            scanned_at=t0,
            current_hash="hash-a",
            state="up_to_date",
            enabled=True,
            finding_counts={"phpstan_error": 2},
        )
    )
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/modules/history/trend")

    assert response.status_code == 200
    body = response.json()
    matching = [
        p for p in body if abs(datetime.fromisoformat(p["scanned_at"]) - t0) < timedelta(seconds=1)
    ]
    assert len(matching) == 1
    assert matching[0]["total_findings"] >= 2

    # Same reasoning as test_fleet_trend.py's own cleanup: this module's
    # "up_to_date" state would otherwise leak into other fleet-wide tests
    # (e.g. an embedding-model change's own "N modules affected" count),
    # since db_session never rolls back between tests.
    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()
