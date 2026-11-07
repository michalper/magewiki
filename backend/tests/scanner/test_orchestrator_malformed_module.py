from pathlib import Path

import pytest

from app.scanner.orchestrator import scan_repository_events


@pytest.mark.asyncio
async def test_scan_reports_a_module_error_event_for_malformed_module_xml(tmp_path: Path, db_session):
    repo_root = tmp_path / "repo"
    module_dir = repo_root / "app" / "code" / "Vendor" / "Broken"
    (module_dir / "etc").mkdir(parents=True)
    (module_dir / "etc" / "module.xml").write_text("<config><unclosed>", encoding="utf-8")

    events = [event async for event in scan_repository_events(str(repo_root), db_session)]

    module_events = [e for e in events if e["event"] == "module"]
    assert len(module_events) == 1
    assert module_events[0]["status"] == "error"
    assert module_events[0]["name"] == "app/code/Vendor/Broken"
    assert "malformed module.xml" in module_events[0]["warning"]

    done_event = next(e for e in events if e["event"] == "done")
    assert any("malformed module.xml" in w for w in done_event["result"].warnings)
    assert done_event["result"].modules_found == 1
    assert done_event["result"].modules_created == 0
