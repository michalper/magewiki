from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModuleHistorySnapshot


@dataclass
class FleetTrendPoint:
    scanned_at: datetime
    total_findings: int


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

    latest_by_module: dict[int, int] = {}
    points: list[FleetTrendPoint] = []
    for module_id, scanned_at, finding_counts in rows:
        latest_by_module[module_id] = sum(finding_counts.values())
        points.append(FleetTrendPoint(scanned_at=scanned_at, total_findings=sum(latest_by_module.values())))
    return points
