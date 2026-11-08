import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Module, ModuleQualityFinding
from app.scanner.orchestrator import scan_repository


def _write_module(module_dir: Path, name: str, license: list[str] | str) -> None:
    (module_dir / "etc").mkdir(parents=True)
    (module_dir / "etc" / "module.xml").write_text(
        f'<?xml version="1.0"?><config><module name="{name}" /></config>', encoding="utf-8"
    )
    (module_dir / "composer.json").write_text(
        json.dumps({"name": f"vendor/{name.lower()}", "license": license}), encoding="utf-8"
    )


@pytest.mark.asyncio
async def test_scan_flags_a_module_with_a_copyleft_license(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"
    _write_module(repo_root / "app" / "code" / "Vendor" / "A", "Vendor_A", "GPL-3.0")

    await scan_repository(str(repo_root), db_session)

    module = await db_session.scalar(
        select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_A")
    )
    findings = (
        await db_session.scalars(
            select(ModuleQualityFinding).where(
                ModuleQualityFinding.module_id == module.id, ModuleQualityFinding.check_type == "license_risk"
            )
        )
    ).all()
    assert len(findings) == 1
    assert "GPL-3.0" in findings[0].message


@pytest.mark.asyncio
async def test_scan_does_not_flag_a_permissive_license(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"
    _write_module(repo_root / "app" / "code" / "Vendor" / "A", "Vendor_A", "MIT")

    await scan_repository(str(repo_root), db_session)

    module = await db_session.scalar(
        select(Module).where(Module.repo_root == str(repo_root), Module.name == "Vendor_A")
    )
    findings = (
        await db_session.scalars(
            select(ModuleQualityFinding).where(
                ModuleQualityFinding.module_id == module.id, ModuleQualityFinding.check_type == "license_risk"
            )
        )
    ).all()
    assert findings == []
