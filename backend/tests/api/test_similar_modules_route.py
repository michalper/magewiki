import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import Chunk, Module


def _vector(active: dict[int, float]) -> list[float]:
    v = [0.0] * 1536
    for i, val in active.items():
        v[i] = val
    return v


async def _make_module(session, suffix: str, name: str) -> Module:
    module = Module(
        repo_root=f"/tmp/similar-route-test-{suffix}",
        name=name,
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
async def test_similar_modules_404_for_unknown_module():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/modules/999999999/similar")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_similar_modules_empty_list_when_not_yet_embedded(db_session):
    suffix = uuid.uuid4().hex[:8]
    module = await _make_module(db_session, suffix, f"NotEmbedded_{suffix}")
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/modules/{module.id}/similar")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_similar_modules_returns_a_real_match(db_session):
    suffix = uuid.uuid4().hex[:8]
    base = int(suffix, 16) % 1500
    target = await _make_module(db_session, f"{suffix}-target", f"Target_{suffix}")
    similar = await _make_module(db_session, f"{suffix}-similar", f"Similar_{suffix}")

    db_session.add_all(
        [
            Chunk(
                module_id=target.id, chunk_type="module", content_hash=f"c-{target.id}",
                text="target module summary", embedding=_vector({base: 1.0}),
            ),
            Chunk(
                module_id=similar.id, chunk_type="module", content_hash=f"c-{similar.id}",
                text="similar module summary", embedding=_vector({base: 0.99, base + 1: 0.01}),
            ),
        ]
    )
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/modules/{target.id}/similar")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["module_id"] == similar.id
    assert body[0]["name"] == similar.name
    assert body[0]["similarity"] > 0.9


@pytest.mark.asyncio
async def test_similar_modules_respects_the_limit_query_param():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/modules/999999999/similar", params={"limit": 100})

    assert response.status_code == 422
