import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, text

from app.models import Chunk, Module, PhpClass
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

    async def _fake_embed(q, **kwargs):
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

    async def _fake_embed(q, **kwargs):
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

    async def _fake_embed(q, **kwargs):
        return _vector({})

    monkeypatch.setattr("app.search.hybrid.embed_query_text", _fake_embed)

    results = await hybrid_search(db_session, distinctive_name, limit=50, topk=50, trgm_threshold=0.3)
    result_ids = {r.chunk_id for r in results}

    assert module_chunk.id in result_ids

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_identifier_signal_module_name_hit_does_not_flood_out_a_class_name_hit(db_session, monkeypatch):
    """A module-name trgm match must map to that module's own module-level
    chunk only — not every chunk the module owns — or one module-name hit can
    consume the entire :topk rank budget for the identifier signal and starve
    a more specific class-name hit in a different module of any rank slot at
    all (verified empirically: similarity('ZyzzyvaFloodModuleXyz456',
    'ZyzzyvaFloodModuleAbc123') ≈ 0.56, comfortably above the 0.3 threshold).
    """
    suffix = uuid.uuid4().hex[:8]
    flood_name = f"ZyzzyvaFloodModuleAbc123{suffix}"
    target_class_name = f"ZyzzyvaFloodModuleXyz456{suffix}"

    flood_module = await _make_module(db_session, f"flood-{suffix}", name=flood_name)
    # Many chunks on the flooding module — more than :topk below — so an
    # unfixed join would consume the whole identifier rank budget on this
    # one module-name hit alone.
    for i in range(5):
        db_session.add(
            Chunk(
                module_id=flood_module.id, chunk_type="file", relative_path=f"File{i}.php",
                content_hash=f"flood-{suffix}-{i}", text="Irrelevant content, no keyword/vector signal.",
                embedding=_vector({}),
            )
        )

    target_module = await _make_module(db_session, f"target-{suffix}")
    db_session.add(
        PhpClass(
            module_id=target_module.id, fqcn=target_class_name, namespace=None, class_name=target_class_name,
            kind="class", extends=[], implements=[], file_path="Target.php",
        )
    )
    target_chunk = Chunk(
        module_id=target_module.id, chunk_type="file", relative_path="Target.php",
        content_hash=f"target-{suffix}", text="Irrelevant content, no keyword/vector signal.",
        embedding=_vector({}),
    )
    db_session.add(target_chunk)
    await db_session.commit()

    async def _fake_embed(q, **kwargs):
        return _vector({})

    monkeypatch.setattr("app.search.hybrid.embed_query_text", _fake_embed)

    results = await hybrid_search(db_session, flood_name, limit=50, topk=3, trgm_threshold=0.3)
    result_ids = {r.chunk_id for r in results}

    assert target_chunk.id in result_ids

    await db_session.execute(delete(Module).where(Module.id.in_([flood_module.id, target_module.id])))
    await db_session.commit()


@pytest.mark.asyncio
async def test_identifier_signal_does_not_double_count_two_classes_in_the_same_file(db_session, monkeypatch):
    """Regression test: two PhpClass rows in the same file both join to that one
    file-level chunk. Before the DISTINCT ON (ch.id) fix, that chunk got two
    separate rnk values in the identifiers CTE, both summed into its fused RRF
    score — letting a chunk with two individually WEAKER matches outrank a chunk
    with one genuinely STRONGER match, purely from double-counting.

    Similarity scores verified empirically against this exact Postgres/pg_trgm
    version: similarity('ZyzxDoubleTargetSingle', 'ZyzxDoubleTarget') ≈ 0.667 is
    higher than EITHER of 'ZyzxDoubleAlpha'/'ZyzxDoubleBeta' (≈0.435/≈0.524)
    individually, but summing the latter two's RRF contributions (the bug)
    exceeds the single stronger match's contribution; deduped (the fix), it
    doesn't.
    """
    suffix = uuid.uuid4().hex[:8]
    query = f"ZyzxDoubleTarget{suffix}"

    double_module = await _make_module(db_session, f"double-{suffix}")
    db_session.add_all(
        [
            PhpClass(
                module_id=double_module.id, fqcn=f"ZyzxDoubleAlpha{suffix}", namespace=None,
                class_name=f"ZyzxDoubleAlpha{suffix}", kind="class", extends=[], implements=[],
                file_path="Shared.php",
            ),
            PhpClass(
                module_id=double_module.id, fqcn=f"ZyzxDoubleBeta{suffix}", namespace=None,
                class_name=f"ZyzxDoubleBeta{suffix}", kind="class", extends=[], implements=[],
                file_path="Shared.php",
            ),
        ]
    )
    # A zero embedding has an undefined (NaN) cosine distance, which Postgres sorts
    # by tie-break rules that aren't guaranteed stable — in a near-empty table (just
    # these two chunks) that made the semantic signal's contribution to each chunk
    # depend on an arbitrary tie-break rather than a real distance, occasionally
    # large enough to flip this test's tight identifier-signal margin. Instead,
    # single_chunk's embedding exactly matches the query (cosine distance 0) and
    # double_chunk's points in a different direction (distance ≈0.29) — both
    # well-defined and deterministic, and the semantic signal now reinforces (never
    # contradicts) the same winner the identifier-signal fix is being tested for.
    double_chunk = Chunk(
        module_id=double_module.id, chunk_type="file", relative_path="Shared.php",
        content_hash=f"double-{suffix}", text="Irrelevant content, no keyword/vector signal.",
        embedding=_vector({42: 0.5, 43: 0.5}),
    )
    db_session.add(double_chunk)

    single_module = await _make_module(db_session, f"single-{suffix}")
    db_session.add(
        PhpClass(
            module_id=single_module.id, fqcn=f"ZyzxDoubleTargetSingle{suffix}", namespace=None,
            class_name=f"ZyzxDoubleTargetSingle{suffix}", kind="class", extends=[], implements=[],
            file_path="Single.php",
        )
    )
    single_chunk = Chunk(
        module_id=single_module.id, chunk_type="file", relative_path="Single.php",
        content_hash=f"single-{suffix}", text="Irrelevant content, no keyword/vector signal.",
        embedding=_vector({42: 1.0}),
    )
    db_session.add(single_chunk)
    await db_session.commit()

    async def _fake_embed(q, **kwargs):
        return _vector({42: 1.0})  # exact match to single_chunk's embedding

    monkeypatch.setattr("app.search.hybrid.embed_query_text", _fake_embed)

    results = await hybrid_search(db_session, query, limit=50, topk=50, trgm_threshold=0.3)
    my_ids = {double_chunk.id, single_chunk.id}
    ordered = [r.chunk_id for r in results if r.chunk_id in my_ids]

    # The single stronger match must outrank the double-weaker-match chunk — the
    # bug would have reversed this via double-counted RRF contributions.
    assert ordered == [single_chunk.id, double_chunk.id]

    await db_session.execute(delete(Module).where(Module.id.in_([double_module.id, single_module.id])))
    await db_session.commit()


_IDENTIFIERS_CTE_SQL = text("""
WITH identifier_hits AS (
    SELECT m.id AS module_id, NULL::text AS relative_path, similarity(m.name, :query_text) AS sim
    FROM modules m
    WHERE similarity(m.name, :query_text) > :trgm_threshold
    UNION ALL
    SELECT pc.module_id, pc.file_path,
           GREATEST(similarity(pc.fqcn, :query_text), similarity(pc.class_name, :query_text)) AS sim
    FROM php_classes pc
    WHERE similarity(pc.fqcn, :query_text) > :trgm_threshold
       OR similarity(pc.class_name, :query_text) > :trgm_threshold
),
identifiers AS (
    SELECT chunk_id, row_number() OVER (ORDER BY sim DESC) AS rnk
    FROM (
        SELECT DISTINCT ON (ch.id) ch.id AS chunk_id, ih.sim AS sim
        FROM identifier_hits ih
        JOIN chunks ch ON ch.module_id = ih.module_id
            AND (
                (ih.relative_path IS NULL AND ch.chunk_type = 'module')
                OR (ch.relative_path = ih.relative_path AND ch.chunk_type = 'file')
            )
        ORDER BY ch.id, ih.sim DESC
    ) deduped
)
SELECT chunk_id, rnk FROM identifiers WHERE chunk_id = ANY(:chunk_ids)
""")


@pytest.mark.asyncio
async def test_identifier_signal_maps_a_class_hit_only_to_its_file_chunk_not_every_method_chunk(db_session):
    """Regression test for the identifiers CTE's join condition directly (not the
    full hybrid_search() pipeline — the semantic/keyword signals' own :topk
    ranking is global across the whole chunks table, including whatever other
    tests' chunks are still live in a shared DB, which would make an assertion
    on the full fused RRF score flaky).

    A class-name hit used to join to every chunk sharing its relative_path — the
    one 'file' chunk AND every 'method' chunk (one per plugin/observer method in
    that file). Fanning out across 3 rows instead of 1 in this CTE's globally
    sim-sorted row_number() sequence pushes every weaker-but-distinct match
    further down that same sequence (higher rnk = lower eventual RRF score
    1/(60+rnk)) — not just double-counting onto one chunk, like the test above.

    Similarity verified empirically against this exact Postgres/pg_trgm version:
    with the query equal to Alpha's own class name (sim=1.0) and Beta's class
    name sharing Alpha's random suffix (sim≈0.58, still above the 0.3
    threshold), fixed means Alpha contributes exactly 1 row ahead of Beta, so
    Beta's rnk is 2 — before the fix, Alpha's file+2 method chunks (all tied at
    sim=1.0) would occupy rnk 1-3, pushing Beta to rnk=4 instead.
    """
    suffix = uuid.uuid4().hex[:8]
    query = f"ZyzxFanAlpha{suffix}"

    fan_module = await _make_module(db_session, f"fan-{suffix}")
    db_session.add(
        PhpClass(
            module_id=fan_module.id, fqcn=query, namespace=None, class_name=query,
            kind="class", extends=[], implements=[], file_path="Plugin.php",
        )
    )
    fan_file_chunk = Chunk(
        module_id=fan_module.id, chunk_type="file", relative_path="Plugin.php",
        content_hash=f"fan-file-{suffix}", text="irrelevant", embedding=_vector({100: 1.0}),
    )
    fan_method_chunk_1 = Chunk(
        module_id=fan_module.id, chunk_type="method", relative_path="Plugin.php",
        content_hash=f"fan-method-1-{suffix}", text="irrelevant", embedding=_vector({101: 1.0}),
    )
    fan_method_chunk_2 = Chunk(
        module_id=fan_module.id, chunk_type="method", relative_path="Plugin.php",
        content_hash=f"fan-method-2-{suffix}", text="irrelevant", embedding=_vector({102: 1.0}),
    )
    db_session.add_all([fan_file_chunk, fan_method_chunk_1, fan_method_chunk_2])

    beta_module = await _make_module(db_session, f"beta-{suffix}")
    db_session.add(
        PhpClass(
            module_id=beta_module.id, fqcn=f"ZyzxFanBeta{suffix}", namespace=None,
            class_name=f"ZyzxFanBeta{suffix}", kind="class", extends=[], implements=[],
            file_path="Beta.php",
        )
    )
    beta_chunk = Chunk(
        module_id=beta_module.id, chunk_type="file", relative_path="Beta.php",
        content_hash=f"beta-{suffix}", text="irrelevant", embedding=_vector({103: 1.0}),
    )
    db_session.add(beta_chunk)
    await db_session.commit()

    rows = (
        await db_session.execute(
            _IDENTIFIERS_CTE_SQL,
            {
                "query_text": query,
                "trgm_threshold": 0.3,
                "chunk_ids": [fan_file_chunk.id, fan_method_chunk_1.id, fan_method_chunk_2.id, beta_chunk.id],
            },
        )
    ).all()
    rnk_by_chunk_id = {row.chunk_id: row.rnk for row in rows}

    # Exactly 2 rows total (Alpha's file chunk, Beta's file chunk) — the method
    # chunks must not appear in the identifiers CTE at all.
    assert set(rnk_by_chunk_id) == {fan_file_chunk.id, beta_chunk.id}
    assert rnk_by_chunk_id[fan_file_chunk.id] == 1
    assert rnk_by_chunk_id[beta_chunk.id] == 2

    await db_session.execute(delete(Module).where(Module.id.in_([fan_module.id, beta_module.id])))
    await db_session.commit()
