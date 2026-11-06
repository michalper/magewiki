import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete

from app.evaluation.ci_dataset import _vector
from app.evaluation.isolated_retrieval import keyword_only_search, vector_only_search
from app.evaluation.metrics import aggregate
from app.models import Chunk, Module
from app.search.hybrid import hybrid_search


async def _make_module(session, suffix: str) -> Module:
    module = Module(
        repo_root=f"/tmp/eval-fast-regression-{suffix}",
        name=f"EvalFastRegressionModule_{suffix}",
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
async def test_hybrid_fusion_beats_either_signal_alone(db_session, monkeypatch):
    """Construct a case where the truly relevant chunk ranks #2 by vector-only AND
    #2 by keyword-only (each beaten by a different noise chunk that is strong on
    exactly one signal), but RRF fusion pulls it to #1 in the hybrid retriever —
    the entire point of combining signals. Proves the eval harness's isolation
    queries and metrics glue are wired correctly, with zero real API calls.
    """
    suffix = uuid.uuid4().hex[:8]
    module = await _make_module(db_session, suffix)
    keyword = f"zyzzyvaspecial{suffix}"

    # Relevant: decent embedding match (not the closest) + one keyword mention
    # (not the strongest).
    target = Chunk(
        module_id=module.id, chunk_type="file", relative_path="target.php",
        content_hash=f"target-{suffix}",
        text=f"This file is the actually relevant one and mentions {keyword} once.",
        embedding=_vector({0: 0.9, 1: 0.1}),
    )
    # Noise: closest embedding match, zero keyword overlap -> wins vector-only,
    # irrelevant to keyword CTE entirely.
    vector_noise = Chunk(
        module_id=module.id, chunk_type="file", relative_path="vector_noise.php",
        content_hash=f"vnoise-{suffix}",
        text="This file is unrelated noise with no special terms at all.",
        embedding=_vector({0: 1.0}),
    )
    # Filler: irrelevant on every signal, but with a semantic similarity strictly
    # between target's and keyword_noise's. In a clean, unpolluted DB (such as a
    # fresh CI Postgres service container — only these 4 rows exist) this is
    # what guarantees keyword_noise lands at semantic rank 4, not rank 3: RRF's
    # 1/(60+rank) arithmetic is close enough that target-vs-keyword_noise would
    # otherwise come down to whether keyword_noise is rank 3 or 4, which with
    # only 3 chunks total is a razor-thin, rank-dependent margin rather than a
    # structural one.
    filler = Chunk(
        module_id=module.id, chunk_type="file", relative_path="filler.php",
        content_hash=f"filler-{suffix}",
        text="This file is filler, also unrelated, with no special terms.",
        embedding=_vector({0: 0.5, 4: 0.5}),
    )
    # Noise: strongest keyword match (repeated), far embedding -> wins keyword-only.
    keyword_noise = Chunk(
        module_id=module.id, chunk_type="file", relative_path="keyword_noise.php",
        content_hash=f"knoise-{suffix}",
        text=f"{keyword} {keyword} {keyword} dominates this unrelated file about {keyword}.",
        embedding=_vector({0: -0.5, 2: 1.0}),
    )
    db_session.add_all([target, vector_noise, filler, keyword_noise])
    await db_session.commit()

    async def _fake_embed(q, **kwargs):
        return _vector({0: 1.0})

    monkeypatch.setattr("app.search.hybrid.embed_query_text", _fake_embed)
    monkeypatch.setattr("app.evaluation.isolated_retrieval.embed_query_text", _fake_embed)

    # A bare keyword, not a sentence: websearch_to_tsquery ANDs multiple words
    # together, which would make every non-matching word in a sentence fail the
    # whole match for every chunk.
    query = keyword
    relevant = {target.id}

    # Generous limit/topk: this dev DB is a long-lived, shared, un-isolated
    # Postgres instance (see tests/conftest.py's db_session — no rollback), so
    # other tests' leftover chunks can otherwise push our own out of a tight
    # top-k before RRF fusion even sees them. Matches the margin used in
    # tests/search/test_hybrid_search.py.
    vector_results = await vector_only_search(db_session, query, limit=200)
    keyword_results = await keyword_only_search(db_session, query, limit=200)
    hybrid_results = await hybrid_search(db_session, query, limit=200, topk=200)

    my_ids = {target.id, vector_noise.id, keyword_noise.id}
    vector_ranked = [r.chunk_id for r in vector_results if r.chunk_id in my_ids]
    keyword_ranked = [r.chunk_id for r in keyword_results if r.chunk_id in my_ids]
    hybrid_ranked = [r.chunk_id for r in hybrid_results if r.chunk_id in my_ids]

    # Sanity: confirm the scenario is actually set up as intended before
    # asserting on the metrics that matter.
    assert vector_ranked[0] == vector_noise.id
    assert keyword_ranked[0] == keyword_noise.id

    vector_metrics = aggregate([(vector_ranked, relevant)], ks=(1,))
    keyword_metrics = aggregate([(keyword_ranked, relevant)], ks=(1,))
    hybrid_metrics = aggregate([(hybrid_ranked, relevant)], ks=(1,))

    assert vector_metrics["recall@1"] == 0.0
    assert keyword_metrics["recall@1"] == 0.0
    assert hybrid_metrics["recall@1"] == 1.0
    assert hybrid_metrics["recall@1"] >= max(vector_metrics["recall@1"], keyword_metrics["recall@1"])

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()
