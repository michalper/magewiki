import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.analyzer.cache import create_cache_entries_bulk, get_or_create_cache_entry, lookup_cache
from app.analyzer.client import LlmCallResult
from app.models import AnalysisCache


@pytest.mark.asyncio
async def test_get_or_create_cache_entry_inserts_a_new_row(db_session):
    content_hash = f"cache-test-{uuid.uuid4().hex[:8]}"
    result = LlmCallResult(response_json={"x": 1}, tokens_in=10, tokens_out=5, cost_usd=Decimal("0.001"))

    cache_id = await get_or_create_cache_entry(db_session, content_hash, "m", "v1", "file_summary", result)
    await db_session.commit()

    row = await db_session.get(AnalysisCache, cache_id)
    assert row is not None
    assert row.content_hash == content_hash


@pytest.mark.asyncio
async def test_get_or_create_cache_entry_returns_the_existing_id_on_conflict(db_session):
    """Regression/race-condition path: on_conflict_do_nothing() means a concurrent
    job that already inserted the identical (content_hash, model, prompt_version,
    kind) row wins -- this call must find and return THAT row's id, not silently
    produce no id or a duplicate.
    """
    content_hash = f"cache-test-race-{uuid.uuid4().hex[:8]}"
    first_result = LlmCallResult(response_json={"x": 1}, tokens_in=10, tokens_out=5, cost_usd=Decimal("0.001"))
    existing_id = await get_or_create_cache_entry(db_session, content_hash, "m", "v1", "file_summary", first_result)
    await db_session.commit()

    second_result = LlmCallResult(response_json={"x": 2}, tokens_in=99, tokens_out=99, cost_usd=Decimal(9))
    returned_id = await get_or_create_cache_entry(db_session, content_hash, "m", "v1", "file_summary", second_result)

    assert returned_id == existing_id

    rows = (
        await db_session.scalars(
            select(AnalysisCache).where(
                AnalysisCache.content_hash == content_hash, AnalysisCache.model == "m",
                AnalysisCache.prompt_version == "v1", AnalysisCache.kind == "file_summary",
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].tokens_in == 10  # the first (winning) insert's data, not the second's


@pytest.mark.asyncio
async def test_create_cache_entries_bulk_inserts_every_row_in_one_statement(db_session):
    """embed_chunks' batched sibling of get_or_create_cache_entry() -- found
    worth adding by a whole-project code review that flagged the per-row
    loop it replaced."""
    prefix = f"cache-bulk-{uuid.uuid4().hex[:8]}"
    entries = [
        (f"{prefix}-a", LlmCallResult(response_json={"embedding": [0.1]}, tokens_in=1, tokens_out=0, cost_usd=Decimal("0.0001"))),
        (f"{prefix}-b", LlmCallResult(response_json={"embedding": [0.2]}, tokens_in=2, tokens_out=0, cost_usd=Decimal("0.0002"))),
    ]

    await create_cache_entries_bulk(db_session, "m", "v1", "embedding", entries)
    await db_session.commit()

    rows = (
        await db_session.scalars(
            select(AnalysisCache).where(AnalysisCache.content_hash.in_([h for h, _r in entries]))
        )
    ).all()
    assert {r.content_hash for r in rows} == {f"{prefix}-a", f"{prefix}-b"}


@pytest.mark.asyncio
async def test_create_cache_entries_bulk_skips_a_row_that_already_exists(db_session):
    """on_conflict_do_nothing per row, same as get_or_create_cache_entry --
    one of the batch's hashes already being cached (e.g. a retried batch
    after a partial failure) must not raise or duplicate it."""
    content_hash = f"cache-bulk-conflict-{uuid.uuid4().hex[:8]}"
    first = LlmCallResult(response_json={"embedding": [0.1]}, tokens_in=1, tokens_out=0, cost_usd=Decimal("0.0001"))
    await get_or_create_cache_entry(db_session, content_hash, "m", "v1", "embedding", first)
    await db_session.commit()

    second = LlmCallResult(response_json={"embedding": [0.9]}, tokens_in=9, tokens_out=0, cost_usd=Decimal("0.0009"))
    await create_cache_entries_bulk(db_session, "m", "v1", "embedding", [(content_hash, second)])
    await db_session.commit()

    rows = (
        await db_session.scalars(select(AnalysisCache).where(AnalysisCache.content_hash == content_hash))
    ).all()
    assert len(rows) == 1
    assert rows[0].tokens_in == 1  # the first (winning) insert's data, not the second's


@pytest.mark.asyncio
async def test_create_cache_entries_bulk_is_a_no_op_for_an_empty_list(db_session):
    await create_cache_entries_bulk(db_session, "m", "v1", "embedding", [])
    await db_session.commit()


@pytest.mark.asyncio
async def test_lookup_cache_finds_an_existing_entry(db_session):
    content_hash = f"cache-test-lookup-{uuid.uuid4().hex[:8]}"
    result = LlmCallResult(response_json={"x": 1}, tokens_in=1, tokens_out=1, cost_usd=Decimal("0.0001"))
    await get_or_create_cache_entry(db_session, content_hash, "m", "v1", "file_summary", result)
    await db_session.commit()

    found = await lookup_cache(db_session, content_hash, "m", "v1", "file_summary")

    assert found is not None
    assert found.content_hash == content_hash


@pytest.mark.asyncio
async def test_lookup_cache_returns_none_when_nothing_matches(db_session):
    found = await lookup_cache(db_session, f"no-such-hash-{uuid.uuid4().hex[:8]}", "m", "v1", "file_summary")

    assert found is None
