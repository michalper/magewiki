from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PackagistCache

# One shared cache table for every Packagist-backed check, 24h TTL — mirrors
# v1's own single `packagist_cache` table/class reused across its advisory
# and abandoned/outdated clients (see docs/v1-port-roadmap.md).
_TTL = timedelta(hours=24)


async def get_cached(session: AsyncSession, cache_key: str) -> dict | None:
    row = await session.get(PackagistCache, cache_key)
    if row is None:
        return None
    if datetime.now(UTC) - row.fetched_at > _TTL:
        return None
    return row.response_json


async def set_cached(session: AsyncSession, cache_key: str, response_json: dict) -> None:
    stmt = insert(PackagistCache).values(
        cache_key=cache_key, response_json=response_json, fetched_at=datetime.now(UTC)
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[PackagistCache.cache_key],
        set_={"response_json": stmt.excluded.response_json, "fetched_at": stmt.excluded.fetched_at},
    )
    await session.execute(stmt)
