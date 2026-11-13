from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Module, ModuleQualityFinding
from app.scanner.orchestrator import scan_repository_events


def _write_module(
    module_dir: Path, name: str, area: str, route_id: str, front_name: str
) -> None:
    (module_dir / "etc" / area).mkdir(parents=True)
    (module_dir / "etc" / "module.xml").write_text(
        f'<?xml version="1.0"?><config><module name="{name}" /></config>', encoding="utf-8"
    )
    (module_dir / "etc" / area / "routes.xml").write_text(
        '<?xml version="1.0"?><config><router id="standard">'
        f'<route id="{route_id}" frontName="{front_name}"><module name="{name}" /></route>'
        "</router></config>",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_scan_flags_a_cross_module_frontname_conflict(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"

    _write_module(repo_root / "app" / "code" / "Vendor" / "A", "Vendor_A", "frontend", "vendor_a", "shared")
    _write_module(repo_root / "app" / "code" / "Vendor" / "B", "Vendor_B", "frontend", "vendor_b", "shared")

    events = [event async for event in scan_repository_events(str(repo_root), db_session)]
    done = next(e for e in events if e["event"] == "done")
    assert done["result"].modules_created == 2

    module_a = await db_session.scalar(
        select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_A")
    )
    module_b = await db_session.scalar(
        select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_B")
    )

    for module in (module_a, module_b):
        findings = (
            await db_session.scalars(
                select(ModuleQualityFinding).where(
                    ModuleQualityFinding.module_id == module.id,
                    ModuleQualityFinding.check_type == "frontname_conflict",
                )
            )
        ).all()
        assert len(findings) == 1
        assert "shared" in findings[0].message
        assert "frontend" in findings[0].message
        assert findings[0].severity == "warning"

    # Route ids are distinct (vendor_a/vendor_b), so route_id_conflict must
    # not also fire for the same pair.
    route_id_findings = (
        await db_session.scalars(
            select(ModuleQualityFinding)
            .join(Module, Module.id == ModuleQualityFinding.module_id)
            .where(ModuleQualityFinding.check_type == "route_id_conflict", Module.repo_root == str(repo_root))
        )
    ).all()
    assert route_id_findings == []


@pytest.mark.asyncio
async def test_scan_flags_a_cross_module_route_id_conflict(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"

    _write_module(repo_root / "app" / "code" / "Vendor" / "A", "Vendor_A", "adminhtml", "shared_id", "vendor-a")
    _write_module(repo_root / "app" / "code" / "Vendor" / "B", "Vendor_B", "adminhtml", "shared_id", "vendor-b")

    async for _event in scan_repository_events(str(repo_root), db_session):
        pass

    findings = (
        await db_session.scalars(
            select(ModuleQualityFinding)
            .join(Module, Module.id == ModuleQualityFinding.module_id)
            .where(ModuleQualityFinding.check_type == "route_id_conflict", Module.repo_root == str(repo_root))
        )
    ).all()
    assert len(findings) == 2
    assert all("shared_id" in f.message and "adminhtml" in f.message for f in findings)


@pytest.mark.asyncio
async def test_scan_does_not_flag_the_same_id_and_frontname_in_different_areas(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"

    _write_module(repo_root / "app" / "code" / "Vendor" / "A", "Vendor_A", "frontend", "shared", "shared")
    _write_module(repo_root / "app" / "code" / "Vendor" / "B", "Vendor_B", "adminhtml", "shared", "shared")

    async for _event in scan_repository_events(str(repo_root), db_session):
        pass

    findings = (
        await db_session.scalars(
            select(ModuleQualityFinding)
            .join(Module, Module.id == ModuleQualityFinding.module_id)
            .where(
                ModuleQualityFinding.check_type.in_(["route_id_conflict", "frontname_conflict"]),
                Module.repo_root == str(repo_root),
            )
        )
    ).all()
    assert findings == []
