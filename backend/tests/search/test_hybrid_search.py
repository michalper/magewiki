import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete

from app.models import Chunk, Module
from app.search.hybrid import hybrid_search


def _vector(active: dict[int, float]) -> list[float]:
    v = [0.0] * 1536
    for i, val in active.items():
        v[i] = val
    return v


async def _make_module(session, suffix: str, name: str | None = None) -> Module:
    module = Module(
        repo_root=f"/tmp/hybrid-search-test-{suffix}",
        name=name or f"HybridTestModule_{suffix}",
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
async def test_semantic_signal_orders_chunks_by_cosine_similarity(db_session, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    module = await _make_module(db_session, suffix)

    close = Chunk(
        module_id=module.id, chunk_type="file", relative_path="close.php",
        content_hash=f"close-{suffix}", text=f"close chunk text {suffix}", embedding=_vector({0: 1.0}),
    )
    orthogonal = Chunk(
        module_id=module.id, chunk_type="file", relative_path="orthogonal.php",
        content_hash=f"orth-{suffix}", text=f"orthogonal chunk text {suffix}", embedding=_vector({1: 1.0}),
    )
    opposite = Chunk(
        module_id=module.id, chunk_type="file", relative_path="opposite.php",
        content_hash=f"opp-{suffix}", text=f"opposite chunk text {suffix}", embedding=_vector({0: -1.0}),
    )
    db_session.add_all([close, orthogonal, opposite])
    await db_session.commit()

    async def _fake_embed(q):
        return _vector({0: 1.0})

    monkeypatch.setattr("app.search.hybrid.embed_query_text", _fake_embed)

    results = await hybrid_search(db_session, f"irrelevant query text {suffix}", limit=50, topk=50)
    my_ids = {close.id, orthogonal.id, opposite.id}
    ordered = [r for r in results if r.chunk_id in my_ids]

    assert [r.chunk_id for r in ordered] == [close.id, orthogonal.id, opposite.id]

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_keyword_signal_surfaces_matching_chunk(db_session, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    module = await _make_module(db_session, suffix)

    distinctive_word = f"zyzzyva{suffix}"
    matching = Chunk(
        module_id=module.id, chunk_type="file", relative_path="matching.php",
        content_hash=f"match-{suffix}",
        text=f"This file handles {distinctive_word} processing for the checkout flow.",
        embedding=_vector({}),
    )
    unrelated = Chunk(
        module_id=module.id, chunk_type="file", relative_path="unrelated.php",
        content_hash=f"unrelated-{suffix}", text="This file does something entirely different.",
        embedding=_vector({}),
    )
    db_session.add_all([matching, unrelated])
    await db_session.commit()

    async def _fake_embed(q):
        return _vector({0: 1.0})

    monkeypatch.setattr("app.search.hybrid.embed_query_text", _fake_embed)

    # Both chunks tie on the (irrelevant, zero) semantic signal, so with a generous
    # topk/limit the vector CTE alone would return every chunk in the table
    # regardless of relevance. What this test actually checks is that the keyword
    # signal breaks that tie in favor of the chunk whose text really matches —
    # so assert relative order among our own two chunks, not absolute inclusion.
    results = await hybrid_search(db_session, distinctive_word, limit=200, topk=200)
    my_ids = {matching.id, unrelated.id}
    ordered = [r.chunk_id for r in results if r.chunk_id in my_ids]

    assert ordered[0] == matching.id

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_identifier_signal_matches_module_name(db_session, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    distinctive_name = f"ZyzzyvaCorp_Shipping{suffix}"
    module = await _make_module(db_session, suffix, name=distinctive_name)

    module_chunk = Chunk(
        module_id=module.id, chunk_type="module", relative_path=None,
        content_hash=f"modchunk-{suffix}", text="A module that ships parcels.",
        embedding=_vector({}),
    )
    db_session.add(module_chunk)
    await db_session.commit()

    async def _fake_embed(q):
        return _vector({})

    monkeypatch.setattr("app.search.hybrid.embed_query_text", _fake_embed)

    results = await hybrid_search(db_session, distinctive_name, limit=50, topk=50, trgm_threshold=0.3)
    result_ids = {r.chunk_id for r in results}

    assert module_chunk.id in result_ids

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()
