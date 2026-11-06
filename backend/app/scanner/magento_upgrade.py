import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from app.scanner.dto import QualityFinding
from app.scanner.magento_github import (
    fetch_release_component_versions,
    fetch_release_php_constraint,
    resolve_latest_release,
)
from app.scanner.semver import constraints_overlap


async def check_magento_upgrade_readiness(
    session: AsyncSession, php_constraint: str | None, requirements: dict[str, str]
) -> list[QualityFinding]:
    """Is this module ready for the latest Magento release? Two signals,
    both against the exact data the target release itself declares (not an
    approximation via "latest on Packagist" — see magento_github.py for why
    that's not available for Magento's own packages):

    - the module's own require.php constraint vs. the target release's
      require.php constraint
    - each magento/* requirement's constraint vs. the exact version that
      package is locked to in the target release

    Fails open (empty list) on any GitHub HTTP error, matching every other
    Phase 10/12 scanner's convention — a flaky external call never fails the
    whole scan.
    """
    tag = await resolve_latest_release(session)
    if tag is None:
        return []

    findings: list[QualityFinding] = []

    magento_requirements = {
        name: constraint for name, constraint in requirements.items() if name.startswith("magento/")
    }
    # Both calls depend only on `tag`, not on each other — fetch concurrently
    # instead of serializing two independent GitHub round trips per module.
    if magento_requirements:
        target_php_constraint, component_versions = await asyncio.gather(
            fetch_release_php_constraint(session, tag),
            fetch_release_component_versions(session, tag),
        )
    else:
        target_php_constraint = await fetch_release_php_constraint(session, tag)
        component_versions = {}

    if (
        php_constraint
        and target_php_constraint
        and not constraints_overlap(php_constraint, target_php_constraint)
    ):
        findings.append(
            QualityFinding(
                check_type="magento_php_incompatible",
                severity="blocking",
                file_path="composer.json",
                line=None,
                message=(
                    f"Requires PHP {php_constraint}, but Magento {tag} needs "
                    f"{target_php_constraint}"
                ),
            )
        )

    if magento_requirements:
        for package_name, declared_constraint in magento_requirements.items():
            locked_version = component_versions.get(package_name)
            if locked_version and not constraints_overlap(declared_constraint, locked_version):
                findings.append(
                    QualityFinding(
                        check_type="magento_version_blocker",
                        severity="blocking",
                        file_path="composer.json",
                        line=None,
                        message=(
                            f"{package_name} {declared_constraint} does not allow "
                            f"Magento {tag}'s {locked_version}"
                        ),
                    )
                )

    return findings
