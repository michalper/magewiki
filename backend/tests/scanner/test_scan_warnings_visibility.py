import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Module
from app.scanner.orchestrator import scan_repository


@pytest.mark.asyncio
async def test_a_failing_module_is_visible_in_scan_level_warnings_and_does_not_block_others(
    tmp_path: Path, demo_store_path: Path, db_session, monkeypatch
):
    """Regression test: a per-module persistence failure used to be recorded only
    on ModuleScanOutcome.warnings (per module), which the UI never renders — only
    ScanResult.warnings (scan-level) is shown, so a scan where a module failed
    looked like a silent, uninformative "0 created, 0 updated" instead of a clear
    error. Also confirms the existing nested-savepoint isolation actually works:
    one module failing must not stop a sibling module from persisting.
    """
    repo_root = tmp_path / "repo"
    good_module = repo_root / "app" / "code" / "Vendor" / "GoodModule"
    bad_module = repo_root / "app" / "code" / "Vendor" / "BadModule"
    shutil.copytree(demo_store_path / "app" / "code" / "Vendor" / "Module", good_module)
    shutil.copytree(demo_store_path / "app" / "code" / "Vendor" / "Module", bad_module)

    (good_module / "etc" / "module.xml").write_text(
        '<?xml version="1.0"?><config><module name="Vendor_GoodModule"/></config>'
    )
    (bad_module / "etc" / "module.xml").write_text(
        '<?xml version="1.0"?><config><module name="Vendor_BadModule"/></config>'
    )

    import app.scanner.orchestrator as orchestrator_module

    real_compute_hashes = orchestrator_module.compute_module_file_hashes

    def _raise_for_bad_module(root: Path):
        if root == bad_module:
            raise RuntimeError("forced failure for test")
        return real_compute_hashes(root)

    monkeypatch.setattr(orchestrator_module, "compute_module_file_hashes", _raise_for_bad_module)

    result = await scan_repository(str(repo_root), db_session)

    assert result.modules_found == 2
    assert result.modules_created == 1
    assert any("Vendor_BadModule" in w and "forced failure for test" in w for w in result.warnings)

    good = await db_session.scalar(
        select(Module).where(Module.repo_root == str(repo_root.resolve()), Module.name == "Vendor_GoodModule")
    )
    bad = await db_session.scalar(
        select(Module).where(Module.repo_root == str(repo_root.resolve()), Module.name == "Vendor_BadModule")
    )
    assert good is not None
    assert bad is None
