from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Module, ModuleQualityFinding
from app.scanner.orchestrator import scan_repository_events


def _write_module(module_dir: Path, name: str, instance_class: str) -> None:
    (module_dir / "etc").mkdir(parents=True)
    (module_dir / "etc" / "module.xml").write_text(
        f'<?xml version="1.0"?><config><module name="{name}" /></config>', encoding="utf-8"
    )
    (module_dir / "etc" / "crontab.xml").write_text(
        f"""<?xml version="1.0"?>
<config>
    <group id="default">
        <job name="shared_job" instance="{instance_class}" method="execute">
            <schedule>0 2 * * *</schedule>
        </job>
    </group>
</config>
""",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_scan_flags_a_cross_module_cron_job_conflict(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"

    _write_module(repo_root / "app" / "code" / "Vendor" / "A", "Vendor_A", "Vendor\\A\\Cron\\Sample")
    _write_module(repo_root / "app" / "code" / "Vendor" / "B", "Vendor_B", "Vendor\\B\\Cron\\Sample")

    events = [event async for event in scan_repository_events(str(repo_root), db_session)]
    done = next(e for e in events if e["event"] == "done")
    assert done["result"].modules_created == 2

    module_a = await db_session.scalar(select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_A"))
    module_b = await db_session.scalar(select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_B"))

    findings_a = (
        await db_session.scalars(
            select(ModuleQualityFinding).where(
                ModuleQualityFinding.module_id == module_a.id,
                ModuleQualityFinding.check_type == "cron_job_conflict",
            )
        )
    ).all()
    findings_b = (
        await db_session.scalars(
            select(ModuleQualityFinding).where(
                ModuleQualityFinding.module_id == module_b.id,
                ModuleQualityFinding.check_type == "cron_job_conflict",
            )
        )
    ).all()

    assert len(findings_a) == 1
    assert len(findings_b) == 1
    assert "shared_job" in findings_a[0].message
    assert findings_a[0].severity == "warning"


@pytest.mark.asyncio
async def test_scan_does_not_flag_agreeing_cron_jobs(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"

    _write_module(repo_root / "app" / "code" / "Vendor" / "A", "Vendor_A", "Vendor\\Shared\\Cron\\Sample")
    _write_module(repo_root / "app" / "code" / "Vendor" / "B", "Vendor_B", "Vendor\\Shared\\Cron\\Sample")

    async for _event in scan_repository_events(str(repo_root), db_session):
        pass

    findings = (
        await db_session.scalars(
            select(ModuleQualityFinding)
            .join(Module, Module.id == ModuleQualityFinding.module_id)
            .where(ModuleQualityFinding.check_type == "cron_job_conflict", Module.repo_root == str(repo_root))
        )
    ).all()
    assert findings == []
