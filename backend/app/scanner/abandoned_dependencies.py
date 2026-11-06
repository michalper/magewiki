import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.scanner.dto import QualityFinding
from app.scanner.packagist_cache import get_cached, set_cached
from app.scanner.semver import constraints_overlap

_P2_URL_TEMPLATE = "https://repo.packagist.org/p2/{package}.json"


async def _fetch_package_info(session: AsyncSession, package_name: str) -> dict | None:
    cache_key = f"p2:{package_name}"
    cached = await get_cached(session, cache_key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(_P2_URL_TEMPLATE.format(package=package_name))
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError:
        return None

    await set_cached(session, cache_key, data)
    return data


def _latest_version_entry(package_name: str, data: dict) -> dict | None:
    versions = data.get("packages", {}).get(package_name) or []
    return versions[0] if versions else None


async def check_abandoned_outdated(
    session: AsyncSession, requirements: dict[str, str]
) -> list[QualityFinding]:
    """Packagist's package-metadata (P2) API — shares the same cache table as
    the CVE check. Non-blocking: staleness/abandonment is tech debt, not a
    known vulnerability, matching v1's own severity judgment.
    """
    findings: list[QualityFinding] = []
    for package_name, declared_constraint in requirements.items():
        data = await _fetch_package_info(session, package_name)
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
