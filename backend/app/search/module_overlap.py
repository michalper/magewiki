from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Module


@dataclass
class OverlapStore:
    module_id: int
    repo_root: str
    current_hash: str | None
    setup_version: str | None
    enabled: bool | None


@dataclass
class ModuleOverlap:
    name: str
    composer_name: str | None
    store_count: int
    version_drift: bool
    stores: list[OverlapStore]


async def find_module_overlap(session: AsyncSession) -> list[ModuleOverlap]:
    """Modules installed under more than one repo_root -- e.g. a shared
    in-house module deployed to several stores, or the same third-party
    module repeated across a fleet. Module.current_hash is computed purely
    from path-relative-to-module-root + file bytes (repo_root never enters
    the hash), so two installs of the literally same version naturally hash
    identically -- version_drift flags when they don't.
    """
    rows = (
        await session.execute(
            select(
                Module.id,
                Module.name,
                Module.composer_name,
                Module.repo_root,
                Module.current_hash,
                Module.setup_version,
                Module.enabled,
            )
        )
    ).all()

    by_name: dict[str, list[Any]] = {}
    for module_id, name, composer_name, repo_root, current_hash, setup_version, enabled in rows:
        by_name.setdefault(name, []).append(
            (module_id, composer_name, repo_root, current_hash, setup_version, enabled)
        )

    entries = []
    for name, group in by_name.items():
        if len({repo_root for _, _, repo_root, _, _, _ in group}) < 2:
            continue
        composer_name = next((c for _, c, _, _, _, _ in group if c), None)
        hashes = {h for _, _, _, h, _, _ in group}
        entries.append(
            ModuleOverlap(
                name=name,
                composer_name=composer_name,
                store_count=len(group),
                version_drift=len(hashes) > 1,
                stores=[
                    OverlapStore(
                        module_id=module_id,
                        repo_root=repo_root,
                        current_hash=current_hash,
                        setup_version=setup_version,
                        enabled=enabled,
                    )
                    for module_id, _, repo_root, current_hash, setup_version, enabled in sorted(
                        group, key=lambda g: g[2]
                    )
                ],
            )
        )

    entries.sort(key=lambda e: (-e.store_count, e.name))
    return entries
