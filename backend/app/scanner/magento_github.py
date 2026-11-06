"""Resolves the latest stable Magento release and its exact dependency
snapshot from Magento's public GitHub repo — not Packagist. Magento's own
packages (magento/framework, magento/module-*, magento/product-community-
edition) are not on public Packagist at all (confirmed empirically: a direct
request 404s); they're distributed only through Magento's private, auth-gated
repo.magento.com Composer repository. That auth is only needed to *install*
packages, though — the public GitHub mirror of the source exposes
composer.json/composer.lock at every release tag with no authentication
needed, which is enough to answer "what does release X require." See
CLAUDE.md's Phase 13 decision note.
"""
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.scanner.packagist_cache import get_cached, set_cached

_HEADERS = {"User-Agent": "magewiki-ai (https://github.com/michalper/magewiki)"}
_RELEASES_LATEST_URL = "https://api.github.com/repos/magento/magento2/releases/latest"
_RAW_FILE_URL_TEMPLATE = "https://raw.githubusercontent.com/magento/magento2/{tag}/{filename}"


async def resolve_latest_release(session: AsyncSession) -> str | None:
    """The tag_name of the latest stable (non-prerelease, non-draft) release."""
    cache_key = "magento-github:latest-release"
    cached = await get_cached(session, cache_key)
    if cached is not None:
        return cached.get("tag_name")

    try:
        async with httpx.AsyncClient(timeout=10.0, headers=_HEADERS) as client:
            response = await client.get(_RELEASES_LATEST_URL)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError:
        return None

    tag_name = data.get("tag_name")
    if not tag_name:
        return None

    await set_cached(session, cache_key, {"tag_name": tag_name})
    return tag_name


async def _fetch_raw_json(session: AsyncSession, tag: str, filename: str) -> dict | None:
    cache_key = f"magento-github:{tag}:{filename}"
    cached = await get_cached(session, cache_key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=30.0, headers=_HEADERS) as client:
            response = await client.get(_RAW_FILE_URL_TEMPLATE.format(tag=tag, filename=filename))
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError:
        return None

    await set_cached(session, cache_key, data)
    return data


async def fetch_release_php_constraint(session: AsyncSession, tag: str) -> str | None:
    """The root composer.json's require.php constraint for a given release tag."""
    data = await _fetch_raw_json(session, tag, "composer.json")
    if data is None:
        return None
    require = data.get("require")
    if not isinstance(require, dict):
        return None
    php_constraint = require.get("php")
    return str(php_constraint) if php_constraint else None


async def fetch_release_component_versions(session: AsyncSession, tag: str) -> dict[str, str]:
    """package name -> exact version, for every magento/* component shipped
    in this release. Comes from composer.json's "replace" map, not
    composer.lock — the Magento monorepo's own composer.lock never lists
    magento/framework or any magento/module-* package in its "packages"
    array (confirmed empirically against a real release): those components
    are "replace"d by the monorepo project itself (self-satisfied from the
    git checkout, not resolved from Packagist), so they simply never appear
    there. "replace" is the one place a release's own composer.json states
    each component's exact version. Reuses the same cached composer.json
    fetch as fetch_release_php_constraint (no extra network call).
    """
    data = await _fetch_raw_json(session, tag, "composer.json")
    if data is None:
        return {}
    replace = data.get("replace")
    if not isinstance(replace, dict):
        return {}
    return {name: str(version) for name, version in replace.items() if name.startswith("magento/")}
