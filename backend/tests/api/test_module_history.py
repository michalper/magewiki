import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import Module, ModuleHistorySnapshot


async def _make_module(session) -> Module:
    suffix = uuid.uuid4().hex[:8]
    module = Module(
        repo_root=f"/tmp/history-test-{suffix}",
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
async def test_history_returns_snapshots_newest_first(db_session):
    module = await _make_module(db_session)
    older = ModuleHistorySnapshot(
        module_id=module.id,
        scanned_at=datetime(2026, 1, 1, tzinfo=UTC),
        current_hash="hash-a",
        state="up_to_date",
        enabled=True,
        finding_counts={"phpstan_error": 3},
    )
    newer = ModuleHistorySnapshot(
        module_id=module.id,
        scanned_at=datetime(2026, 2, 1, tzinfo=UTC),
        current_hash="hash-b",
        state="up_to_date",
        enabled=True,
        finding_counts={"phpstan_error": 1},
    )
    db_session.add_all([older, newer])
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/modules/{module.id}/history")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["current_hash"] == "hash-b"
    assert body[1]["current_hash"] == "hash-a"


@pytest.mark.asyncio
async def test_history_404_for_unknown_module():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/modules/999999999/history")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_history_empty_list_for_a_module_with_no_snapshots(db_session):
    module = await _make_module(db_session)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/modules/{module.id}/history")

    assert response.status_code == 200
    assert response.json() == []
