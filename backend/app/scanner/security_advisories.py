from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.scanner.dto import QualityFinding
from app.scanner.packagist_cache import fetch_many_with_cache
from app.scanner.semver import constraints_overlap

_ADVISORIES_URL = "https://packagist.org/api/security-advisories/"


def _cache_key(package_name: str) -> str:
    return f"advisories:{package_name}"


async def _fetch_from_packagist(package_name: str) -> dict[str, Any] | None:
    """HTTP-only, no session — safe to run concurrently across packages, unlike
    packagist_cache.py's get_cached/set_cached which share the scan's one AsyncSession.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(_ADVISORIES_URL, params={"packages[]": package_name})
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return data
    except httpx.HTTPError:
        return None


def _advisories_for_package(data: dict[str, Any], package_name: str) -> list[dict[str, Any]]:
    # Packagist returns "advisories": {} as a dict keyed by package name when
    # there are results, but as an empty *list* `[]` when there are none.
    advisories = data.get("advisories")
    if not isinstance(advisories, dict):
        return []
    result: list[dict[str, Any]] = advisories.get(package_name, [])
    return result


async def check_security_advisories(
    session: AsyncSession, requirements: dict[str, str]
) -> list[QualityFinding]:
    """Packagist's own public, unauthenticated aggregation of the
    FriendsOfPHP/security-advisories feed — not OSV.dev, not a bespoke CVE
    database (verified against v1's production implementation, see
    docs/v1-port-roadmap.md). A package is only flagged if its declared
    constraint actually overlaps the advisory's affected-version range, not
    on name match alone.
    """
    data_by_package = await fetch_many_with_cache(session, list(requirements), _cache_key, _fetch_from_packagist)

    findings: list[QualityFinding] = []
    for package_name, declared_constraint in requirements.items():
        data = data_by_package.get(package_name)
        advisories = _advisories_for_package(data, package_name) if data is not None else []
        for advisory in advisories:
            affected = advisory.get("affectedVersions")
            if not affected or not constraints_overlap(declared_constraint, affected):
                continue
            cve = advisory.get("cve") or advisory.get("advisoryId") or "unknown advisory"
            title = advisory.get("title", "")
            link = advisory.get("link", "")
            message = f"{cve} — {title}" + (f" ({link})" if link else "")
            findings.append(
                QualityFinding(
                    check_type="security_advisory",
                    severity="blocking",
                    file_path="composer.json",
                    line=None,
                    message=message,
                )
            )
    return findings
