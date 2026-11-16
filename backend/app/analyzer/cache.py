from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyzer.client import LlmCallResult
from app.models import AnalysisCache


async def lookup_cache(
    session: AsyncSession, content_hash: str, model: str, prompt_version: str, kind: str
) -> AnalysisCache | None:
    return await session.scalar(
        select(AnalysisCache).where(
            AnalysisCache.content_hash == content_hash,
            AnalysisCache.model == model,
            AnalysisCache.prompt_version == prompt_version,
            AnalysisCache.kind == kind,
        )
    )


async def get_or_create_cache_entry(
    session: AsyncSession, content_hash: str, model: str, prompt_version: str, kind: str, result: LlmCallResult
) -> int:
    insert_stmt = (
        pg_insert(AnalysisCache)
        .values(
            content_hash=content_hash,
            model=model,
            prompt_version=prompt_version,
            kind=kind,
            response=result.response_json,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
        )
        .on_conflict_do_nothing(index_elements=["content_hash", "model", "prompt_version", "kind"])
        .returning(AnalysisCache.id)
    )
    inserted = (await session.execute(insert_stmt)).first()
    if inserted is not None:
        return inserted.id

    existing_id = await session.scalar(
        select(AnalysisCache.id).where(
            AnalysisCache.content_hash == content_hash,
            AnalysisCache.model == model,
            AnalysisCache.prompt_version == prompt_version,
            AnalysisCache.kind == kind,
        )
    )
    if existing_id is None:
        # on_conflict_do_nothing() only skips the insert because a row with this
        # exact (content_hash, model, prompt_version, kind) already exists -- the
        # fallback select just above is looking it up by that same key, so coming
        # back empty would mean the unique constraint fired against a row this
        # query can't see, which is a bug in this function, not a normal runtime
        # condition to swallow.
        raise AssertionError(  # pragma: no cover - defensive; the race described above
            f"AnalysisCache conflict on ({content_hash!r}, {model!r}, {prompt_version!r}, {kind!r}) "
            "but no existing row was found"
        )
    return existing_id
