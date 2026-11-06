import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.scanner.dto import QualityFinding
from app.scanner.packagist_cache import get_cached, set_cached
from app.scanner.semver import constraints_overlap

_ADVISORIES_URL = "https://packagist.org/api/security-advisories/"


async def _fetch_advisories(session: AsyncSession, package_name: str) -> list[dict]:
    cache_key = f"advisories:{package_name}"
    cached = await get_cached(session, cache_key)
    if cached is not None:
        return _advisories_for_package(cached, package_name)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(_ADVISORIES_URL, params={"packages[]": package_name})
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError:
        return []

    await set_cached(session, cache_key, data)
    return _advisories_for_package(data, package_name)


def _advisories_for_package(data: dict, package_name: str) -> list[dict]:
    # Packagist returns "advisories": {} as a dict keyed by package name when
    # there are results, but as an empty *list* `[]` when there are none.
    advisories = data.get("advisories")
    if not isinstance(advisories, dict):
        return []
    return advisories.get(package_name, [])


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
    findings: list[QualityFinding] = []
    for package_name, declared_constraint in requirements.items():
        advisories = await _fetch_advisories(session, package_name)
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
