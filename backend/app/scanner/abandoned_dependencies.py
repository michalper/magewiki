import asyncio
import re

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.scanner.dto import QualityFinding
from app.scanner.packagist_cache import get_cached, set_cached
from app.scanner.semver import constraints_overlap

_P2_URL_TEMPLATE = "https://repo.packagist.org/p2/{package}.json"

# Composer's own stability vocabulary (minimum-stability: dev < alpha < beta < RC <
# stable). Packagist's P2 API lists versions newest-first but does NOT filter by
# stability — confirmed live: symfony/console's P2 response lists "v8.2.0-BETA1"
# ahead of the true latest stable "v8.1.11". Taking versions[0] unfiltered produces a
# false outdated_dependency finding for a module already on the newest stable release.
_PRERELEASE_RE = re.compile(r"-(dev|alpha|beta|rc)", re.IGNORECASE)


def _cache_key(package_name: str) -> str:
    return f"p2:{package_name}"


async def _fetch_from_packagist(package_name: str) -> dict | None:
    """HTTP-only, no session — safe to run concurrently across packages,
    unlike get_cached/set_cached below which share the scan's one AsyncSession.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(_P2_URL_TEMPLATE.format(package=package_name))
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError:
        return None


async def _fetch_package_info_for_all(session: AsyncSession, package_names: list[str]) -> dict[str, dict]:
    """Three phases, each session-safe: (1) sequential cache reads — the only
    way to touch one shared AsyncSession from a batch of packages, (2)
    concurrent HTTP fetches for the cache misses, now off the session
    entirely, (3) sequential cache writes for what was just fetched (a 404 or
    HTTP error isn't cached, same as before — only a real response is).
    """
    data_by_package: dict[str, dict] = {}
    misses: list[str] = []
    for package_name in package_names:
        cached = await get_cached(session, _cache_key(package_name))
        if cached is not None:
            data_by_package[package_name] = cached
        else:
            misses.append(package_name)

    if misses:
        fetched = await asyncio.gather(*(_fetch_from_packagist(name) for name in misses))
        for package_name, data in zip(misses, fetched, strict=True):
            if data is not None:
                await set_cached(session, _cache_key(package_name), data)
                data_by_package[package_name] = data

    return data_by_package


def _latest_version_entry(package_name: str, data: dict) -> dict | None:
    versions = data.get("packages", {}).get(package_name) or []
    for entry in versions:
        version = entry.get("version", "")
        if not _PRERELEASE_RE.search(version):
            return entry
    # Every listed version is a pre-release (e.g. a package with no stable release
    # yet) — fall back to the newest one rather than reporting nothing.
    return versions[0] if versions else None


async def check_abandoned_outdated(
    session: AsyncSession, requirements: dict[str, str]
) -> list[QualityFinding]:
    """Packagist's package-metadata (P2) API — shares the same cache table as
    the CVE check. Non-blocking: staleness/abandonment is tech debt, not a
    known vulnerability, matching v1's own severity judgment.
    """
    data_by_package = await _fetch_package_info_for_all(session, list(requirements))

    findings: list[QualityFinding] = []
    for package_name, declared_constraint in requirements.items():
        data = data_by_package.get(package_name)
        if data is None:
            continue
        latest = _latest_version_entry(package_name, data)
        if latest is None:
            continue

        abandoned = latest.get("abandoned")
        if abandoned:
            suffix = f" — use {abandoned} instead" if isinstance(abandoned, str) else ""
            findings.append(
                QualityFinding(
                    check_type="abandoned_dependency",
                    severity="warning",
                    file_path="composer.json",
                    line=None,
                    message=f"{package_name} is abandoned{suffix}",
                )
            )
            continue  # an abandoned package's "latest" isn't a meaningful outdated baseline

        latest_version = latest.get("version")
        if latest_version and not constraints_overlap(declared_constraint, latest_version):
            findings.append(
                QualityFinding(
                    check_type="outdated_dependency",
                    severity="warning",
                    file_path="composer.json",
                    line=None,
                    message=(
                        f"{package_name} {declared_constraint} does not allow "
                        f"the latest release {latest_version}"
                    ),
                )
            )
    return findings
