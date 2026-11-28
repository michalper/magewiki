from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Module, ModuleHistorySnapshot


@dataclass
class FleetDigestModuleChange:
    module_id: int
    module_name: str
    previous_total: int
    current_total: int


@dataclass
class FleetDigest:
    window_start: datetime
    new_modules: list[tuple[int, str]] = field(default_factory=list)
    changed_modules: list[FleetDigestModuleChange] = field(default_factory=list)
    total_delta: int = 0


async def get_fleet_digest(session: AsyncSession, window_start: datetime) -> FleetDigest:
    """Fleet-wide (no repo_root filter, same as fleet_trend.get_fleet_trend)
    summary of what changed in module_history_snapshots since `window_start`.

    One pass over every snapshot row, oldest first: for each module_id we
    track its last-known total finding count strictly before the window
    (the "previous" baseline) and its last-known total overall (the
    "current" state, since rows are insert-only and `scanned_at` is always
    the insert-time `now()` -- see app/scanner/history.py). A module whose
    very first row ever is already inside the window has no baseline, so it
    is reported as newly-scanned rather than as a 0->N change.

    Only modules with at least one snapshot row at or after `window_start`
    are "touched" this week -- a module with no activity in the window is
    silent, by construction, even though it still has a `latest_overall`
    entry from some earlier pass.
    """
    rows = (
        await session.execute(
            select(
                ModuleHistorySnapshot.module_id,
                Module.name,
                ModuleHistorySnapshot.scanned_at,
                ModuleHistorySnapshot.finding_counts,
            )
            .join(Module, Module.id == ModuleHistorySnapshot.module_id)
            .order_by(ModuleHistorySnapshot.scanned_at.asc())
        )
    ).all()

    names: dict[int, str] = {}
    latest_before: dict[int, int] = {}
    latest_overall: dict[int, int] = {}
    seen_ever: set[int] = set()
    first_seen_in_window: set[int] = set()
    touched: set[int] = set()

    for module_id, module_name, scanned_at, finding_counts in rows:
        names[module_id] = module_name
        total = sum(finding_counts.values())

        if module_id not in seen_ever and scanned_at >= window_start:
            first_seen_in_window.add(module_id)
        seen_ever.add(module_id)

        if scanned_at < window_start:
            latest_before[module_id] = total
        else:
            touched.add(module_id)

        latest_overall[module_id] = total

    new_modules = sorted(
        ((module_id, names[module_id]) for module_id in first_seen_in_window), key=lambda pair: pair[1]
    )

    changed_modules = []
    total_delta = 0
    for module_id in touched:
        previous_total = latest_before.get(module_id, 0)
        current_total = latest_overall[module_id]
        total_delta += current_total - previous_total
        if module_id not in first_seen_in_window and current_total != previous_total:
            changed_modules.append(
                FleetDigestModuleChange(
                    module_id=module_id,
                    module_name=names[module_id],
                    previous_total=previous_total,
                    current_total=current_total,
                )
            )
    changed_modules.sort(key=lambda change: change.module_name)

    return FleetDigest(
        window_start=window_start,
        new_modules=new_modules,
        changed_modules=changed_modules,
        total_delta=total_delta,
    )
