from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModuleHistorySnapshot


@dataclass
class FleetTrendPoint:
    scanned_at: datetime
    total_findings: int
    counts: dict[str, int]


async def get_fleet_trend(session: AsyncSession) -> list[FleetTrendPoint]:
    """One point per module_history_snapshots row, fleet-wide, oldest first --
    "is the whole fleet getting better or worse," not just one module's own
    history (GET /modules/{id}/history already answers that). No new
    scanning or parsing: Phase 16 already writes a snapshot on every change.

    module_history_snapshots is deduplicated per module (one row per
    *change*, not per scan -- see app/scanner/history.py), so there's no
    single "fleet state at date X" to read directly: reconstructing one
    means carrying each module's own last-known finding_counts forward as
    the combined timeline advances. Done here in Python rather than a SQL
    lateral join -- simpler and safer for a timeline this sparse (snapshot
    *events*, not daily samples), and the whole fleet's history comfortably
    fits in memory at this project's scale.

    `counts` carries the same per-check_type breakdown forward, not just its
    sum -- `total_findings` is now derived from it (sum(counts.values())),
    kept as its own field so existing consumers (FleetTrendChart) don't need
    to change. A check_type that drops to 0 is removed from `counts` rather
    than kept at 0, so a point's keys are always "categories with real,
    current findings," not every category ever seen.
    """
    rows = (
        await session.execute(
            select(
                ModuleHistorySnapshot.module_id,
                ModuleHistorySnapshot.scanned_at,
                ModuleHistorySnapshot.finding_counts,
            ).order_by(ModuleHistorySnapshot.scanned_at.asc())
        )
    ).all()

    latest_by_module: dict[int, dict[str, int]] = {}
    fleet_counts: dict[str, int] = {}
    points: list[FleetTrendPoint] = []
    for module_id, scanned_at, finding_counts in rows:
        previous = latest_by_module.get(module_id, {})
        for check_type, count in previous.items():
            fleet_counts[check_type] = fleet_counts.get(check_type, 0) - count
        for check_type, count in finding_counts.items():
            fleet_counts[check_type] = fleet_counts.get(check_type, 0) + count
        latest_by_module[module_id] = dict(finding_counts)

        snapshot_counts = {k: v for k, v in fleet_counts.items() if v != 0}
        points.append(
            FleetTrendPoint(
                scanned_at=scanned_at, total_findings=sum(snapshot_counts.values()), counts=snapshot_counts
            )
        )
    return points
