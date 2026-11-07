import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db import async_session_factory
from app.main import app
from app.models import Module


@pytest.fixture
async def overlap_fixture(db_session):
    suffix = uuid.uuid4().hex[:8]
    repo_a = f"/tmp/overlap-a-{suffix}"
    repo_b = f"/tmp/overlap-b-{suffix}"
    repo_c = f"/tmp/overlap-c-{suffix}"

    def module(
        repo_root: str, name: str, current_hash: str, enabled: bool, setup_version: str | None = None
    ) -> Module:
        return Module(
            repo_root=repo_root,
            name=name,
            composer_name=f"vendor/{name.lower()}",
            path=".",
            source_type="standalone",
            state="up_to_date",
            current_hash=current_hash,
            setup_version=setup_version,
            enabled=enabled,
            has_readme=False,
            has_tests=False,
            last_scanned_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

    shared_same_version = f"Shared_{suffix}"
    drifted = f"Drifted_{suffix}"
    unique = f"Unique_{suffix}"

    rows = [
        module(repo_a, shared_same_version, "hash1", True, "2.1.3"),
        module(repo_b, shared_same_version, "hash1", True, "2.1.3"),
        module(repo_a, drifted, "hash-old", True, "2.0.9"),
        module(repo_b, drifted, "hash-new", True, "2.1.0"),
        module(repo_c, drifted, "hash-new", False, "2.1.0"),
        module(repo_a, unique, "hash-only", True, "1.0.0"),
    ]
    db_session.add_all(rows)
    await db_session.commit()

    yield {"shared_same_version": shared_same_version, "drifted": drifted, "unique": unique}

    async with async_session_factory() as cleanup_session:
        await cleanup_session.execute(delete(Module).where(Module.id.in_([m.id for m in rows])))
        await cleanup_session.commit()


@pytest.mark.asyncio
async def test_a_module_present_under_only_one_repo_root_is_excluded(overlap_fixture):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/modules/overlap")

    assert response.status_code == 200
    names = {e["name"] for e in response.json()}
    assert overlap_fixture["unique"] not in names


@pytest.mark.asyncio
async def test_a_module_with_the_same_hash_across_stores_has_no_version_drift(overlap_fixture):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/modules/overlap")

    by_name = {e["name"]: e for e in response.json()}
    entry = by_name[overlap_fixture["shared_same_version"]]
    assert entry["store_count"] == 2
    assert entry["version_drift"] is False
    assert {s["current_hash"] for s in entry["stores"]} == {"hash1"}


@pytest.mark.asyncio
async def test_a_module_with_different_hashes_across_stores_flags_version_drift(overlap_fixture):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/modules/overlap")

    by_name = {e["name"]: e for e in response.json()}
    entry = by_name[overlap_fixture["drifted"]]
    assert entry["store_count"] == 3
    assert entry["version_drift"] is True
    assert {s["current_hash"] for s in entry["stores"]} == {"hash-old", "hash-new"}
    assert {s["setup_version"] for s in entry["stores"]} == {"2.0.9", "2.1.0"}
