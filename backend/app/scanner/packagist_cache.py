import asyncio
from collections.abc import Awaitable, Callable
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


async def fetch_many_with_cache(
    session: AsyncSession,
    keys: list[str],
    cache_key: Callable[[str], str],
    fetch_one: Callable[[str], Awaitable[dict | None]],
) -> dict[str, dict]:
    """Three phases, each session-safe: (1) sequential cache reads — the only
    way to touch one shared AsyncSession from a batch of keys, (2) concurrent
    fetches for the cache misses, now off the session entirely (fetch_one must
    not itself touch `session`), (3) sequential cache writes for what was just
    fetched (a miss that still comes back None — a 404 or HTTP error — isn't
    cached, only a real response is). Shared by every Packagist-backed check
    (security advisories, abandoned/outdated) so this caching/concurrency
    shape lives in one place instead of being copy-pasted per check.
    """
    data_by_key: dict[str, dict] = {}
    misses: list[str] = []
    for key in keys:
        cached = await get_cached(session, cache_key(key))
        if cached is not None:
            data_by_key[key] = cached
        else:
            misses.append(key)

    if misses:
        fetched = await asyncio.gather(*(fetch_one(key) for key in misses))
        for key, data in zip(misses, fetched, strict=True):
            if data is not None:
                await set_cached(session, cache_key(key), data)
                data_by_key[key] = data

    return data_by_key
