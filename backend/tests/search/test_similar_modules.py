import uuid
from datetime import UTC, datetime

import pytest

from app.models import Chunk, Module
from app.search.similar_modules import find_similar_modules


def _vector(active: dict[int, float]) -> list[float]:
    v = [0.0] * 1536
    for i, val in active.items():
        v[i] = val
    return v


def _base_dim(suffix: str) -> int:
    """A per-test pseudo-random dimension index, derived from the test's own
    uuid suffix. find_similar_modules is deliberately fleet-wide (see its
    own docstring), and this project's db_session fixture (tests/conftest.py)
    never rolls back between tests -- every committed Chunk row from every
    earlier test in this file (and this whole pytest run) is still real,
    queryable data. A fixed dimension like 0 would make every test's
    "identical vector" collide with every other test's, exactly like two
    real near-duplicate modules -- basing each test's own vectors on its own
    random suffix keeps different tests' clusters orthogonal to each other.
    """
    return int(suffix, 16) % 1500


async def _make_module(session, suffix: str, name: str | None = None, composer_name: str | None = None) -> Module:
    module = Module(
        repo_root=f"/tmp/similar-modules-test-{suffix}",
        name=name or f"SimilarTestModule_{suffix}",
        composer_name=composer_name,
        path=".",
        source_type="standalone",
        state="up_to_date",
        current_hash=f"hash-{suffix}",
        last_scanned_at=datetime.now(UTC),
    )
    session.add(module)
    await session.flush()
    return module


async def _add_module_chunk(session, module: Module, embedding: list[float]) -> None:
    session.add(
        Chunk(
            module_id=module.id,
            chunk_type="module",
            content_hash=f"module-chunk-{module.id}",
            text=f"module summary for {module.name}",
            embedding=embedding,
        )
    )


@pytest.mark.asyncio
async def test_returns_empty_when_target_module_has_no_module_chunk(db_session):
    suffix = uuid.uuid4().hex[:8]
    module = await _make_module(db_session, suffix)
    await db_session.commit()

    assert await find_similar_modules(db_session, module.id) == []


@pytest.mark.asyncio
async def test_orders_by_cosine_similarity_and_applies_the_threshold(db_session):
    suffix = uuid.uuid4().hex[:8]
    base = _base_dim(suffix)
    target = await _make_module(db_session, f"{suffix}-target")
    close = await _make_module(db_session, f"{suffix}-close")
    far = await _make_module(db_session, f"{suffix}-far")

    await _add_module_chunk(db_session, target, _vector({base: 1.0}))
    await _add_module_chunk(db_session, close, _vector({base: 0.99, base + 1: 0.01}))  # nearly identical
    await _add_module_chunk(db_session, far, _vector({base + 1: 1.0}))  # orthogonal -- below threshold
    await db_session.commit()

    results = await find_similar_modules(db_session, target.id, min_similarity=0.5)

    assert [r.module_id for r in results] == [close.id]
    assert results[0].similarity > 0.9


@pytest.mark.asyncio
async def test_excludes_a_match_with_the_same_composer_name(db_session):
    suffix = uuid.uuid4().hex[:8]
    base = _base_dim(suffix)
    target = await _make_module(db_session, f"{suffix}-target", composer_name="vendor/shared-package")
    same_package = await _make_module(
        db_session, f"{suffix}-same-package", composer_name="vendor/shared-package"
    )
    different_package = await _make_module(
        db_session, f"{suffix}-different-package", composer_name="vendor/other-package"
    )

    identical_vector = _vector({base: 1.0})
    await _add_module_chunk(db_session, target, identical_vector)
    await _add_module_chunk(db_session, same_package, identical_vector)
    await _add_module_chunk(db_session, different_package, identical_vector)
    await db_session.commit()

    results = await find_similar_modules(db_session, target.id, min_similarity=0.5)

    assert [r.module_id for r in results] == [different_package.id]


@pytest.mark.asyncio
async def test_falls_back_to_name_when_composer_name_is_null_for_the_exclusion(db_session):
    suffix = uuid.uuid4().hex[:8]
    base = _base_dim(suffix)
    # Same literal name for both, but still each module's own unique suffix
    # in the *repo_root* (via _make_module) so they're still distinguishable
    # rows -- only `name` collides, which is the thing under test.
    name = f"Vendor_SamePackage_{suffix}"
    target = await _make_module(db_session, f"{suffix}-target", name=name, composer_name=None)
    same_name = await _make_module(db_session, f"{suffix}-dup", name=name, composer_name=None)

    identical_vector = _vector({base: 1.0})
    await _add_module_chunk(db_session, target, identical_vector)
    await _add_module_chunk(db_session, same_name, identical_vector)
    await db_session.commit()

    results = await find_similar_modules(db_session, target.id, min_similarity=0.5)

    assert results == []


@pytest.mark.asyncio
async def test_respects_the_limit(db_session):
    suffix = uuid.uuid4().hex[:8]
    base = _base_dim(suffix)
    target = await _make_module(db_session, f"{suffix}-target")
    await _add_module_chunk(db_session, target, _vector({base: 1.0}))

    others = []
    for i in range(5):
        other = await _make_module(db_session, f"{suffix}-other-{i}")
        await _add_module_chunk(db_session, other, _vector({base: 0.99, base + 1 + i: 0.01}))
        others.append(other)
    await db_session.commit()

    results = await find_similar_modules(db_session, target.id, limit=3, min_similarity=0.5)

    assert len(results) == 3
