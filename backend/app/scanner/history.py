from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Module, ModuleHistorySnapshot, ModuleQualityFinding
from app.scanner.alerts import ModuleAlert, compute_alert_increases


@dataclass
class ModuleHistoryState:
    current_hash: str
    state: str
    enabled: bool | None
    finding_counts: dict[str, int]


def snapshot_changed(previous: ModuleHistoryState | None, current: ModuleHistoryState) -> bool:
    """True when a new module_history_snapshots row should be written --
    either there's no snapshot yet (first scan, establishes a baseline) or
    something about the module's state genuinely differs from the last one
    recorded. Keeps the table from growing on every routine no-op rescan --
    the exact unbounded-growth failure CLAUDE.md's "Operational lessons"
    section already names from v1's own production history (a 3.7GB ->
    822MB cleanup) -- a module that hasn't changed gets no new row.
    """
    if previous is None:
        return True
    return (
        previous.current_hash != current.current_hash
        or previous.state != current.state
        or previous.enabled != current.enabled
        or previous.finding_counts != current.finding_counts
    )


async def _finding_counts_by_module(session: AsyncSession, root: Path) -> dict[int, dict[str, int]]:
    """check_type counts grouped by module_id, scoped to one repo_root --
    the scanner-layer analog of modules.py's own _quality_finding_counts_by_module,
    which is whole-DB and lives in the API layer (not importable from here
    without a layering violation).
    """
    rows = await session.execute(
        select(ModuleQualityFinding.module_id, ModuleQualityFinding.check_type, func.count(ModuleQualityFinding.id))
        .join(Module, Module.id == ModuleQualityFinding.module_id)
        .where(Module.repo_root == str(root))
        .group_by(ModuleQualityFinding.module_id, ModuleQualityFinding.check_type)
    )
    counts: dict[int, dict[str, int]] = {}
    for module_id, check_type, count in rows:
        counts.setdefault(module_id, {})[check_type] = count
    return counts


async def write_history_snapshots(
    session: AsyncSession, root: Path, alertable_check_types: tuple[str, ...] = ()
) -> list[ModuleAlert]:
    """Writes one module_history_snapshots row per module in `root` whose
    hash/state/enabled/finding_counts changed since its own last snapshot
    (or has none yet). Must run after Phase C's cross-module conflict
    detection, not alongside the per-module persist loop -- a module's
    finding_counts aren't complete until conflicts involving it (which
    recompute fleet-wide, not per-module) have been detected and persisted.

    Returns the Phase 18 alert-worthy increases found along the way (one
    entry per module with at least one) -- this is the one place that
    already holds a module's previous and current finding_counts side by
    side with no extra query, so computing the diff here is free. An empty
    `alertable_check_types` (the caller's default) always returns [].
    """
    module_rows = (
        await session.execute(
            select(Module.id, Module.name, Module.current_hash, Module.state, Module.enabled).where(
                Module.repo_root == str(root)
            )
        )
    ).all()

    finding_counts_by_module = await _finding_counts_by_module(session, root)
    alerts: list[ModuleAlert] = []

    for module_id, module_name, current_hash, state, enabled in module_rows:
        current = ModuleHistoryState(
            current_hash=current_hash,
            state=state,
            enabled=enabled,
            finding_counts=finding_counts_by_module.get(module_id, {}),
        )

        latest = await session.scalar(
            select(ModuleHistorySnapshot)
            .where(ModuleHistorySnapshot.module_id == module_id)
            .order_by(ModuleHistorySnapshot.scanned_at.desc())
            .limit(1)
        )
        previous = (
            ModuleHistoryState(
                current_hash=latest.current_hash,
                state=latest.state,
                enabled=latest.enabled,
                finding_counts=latest.finding_counts,
            )
            if latest is not None
            else None
        )

        if snapshot_changed(previous, current):
            session.add(
                ModuleHistorySnapshot(
                    module_id=module_id,
                    current_hash=current.current_hash,
                    state=current.state,
                    enabled=current.enabled,
                    finding_counts=current.finding_counts,
                )
            )

        if alertable_check_types:
            increases = compute_alert_increases(
                previous.finding_counts if previous else None,
                current.finding_counts,
                alertable_check_types,
            )
            if increases:
                alerts.append(ModuleAlert(module_id=module_id, module_name=module_name, increases=increases))

    await session.commit()
    return alerts
