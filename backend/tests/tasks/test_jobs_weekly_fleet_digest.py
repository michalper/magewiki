import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.config import settings
from app.models import Module, ModuleHistorySnapshot
from app.tasks.jobs import weekly_fleet_digest

# weekly_fleet_digest's window is always "now - 7 days" (not injectable), so
# unlike tests/search/test_fleet_digest.py's own tests this can't isolate
# itself with a far-future anchor -- other tests' real-time activity may
# also fall inside the real last 7 days. send_fleet_digest is faked to
# capture the computed FleetDigest, and the assertion only checks that
# *this* test's own module is present in it, same spirit as
# tests/scanner/test_orchestrator_history.py's alert-webhook job tests.


async def _make_module(session, suffix: str) -> Module:
    module = Module(
        repo_root=f"/tmp/weekly-digest-job-test-{suffix}",
        name=f"Vendor_{suffix}",
        path=".",
        source_type="standalone",
        state="up_to_date",
        current_hash=f"hash-{suffix}",
        last_scanned_at=datetime.now(UTC),
    )
    session.add(module)
    await session.flush()
    return module


@pytest.mark.asyncio
async def test_weekly_fleet_digest_reports_a_newly_scanned_module(db_session, monkeypatch):
    sent = []

    async def _fake_send(webhook_url, digest):
        sent.append((webhook_url, digest))

    monkeypatch.setattr("app.tasks.jobs.send_fleet_digest", _fake_send)
    monkeypatch.setattr(settings, "digest_webhook_url", "https://example.com/webhook")

    suffix = uuid.uuid4().hex[:8]
    module = await _make_module(db_session, suffix)
    db_session.add(
        ModuleHistorySnapshot(
            module_id=module.id,
            scanned_at=datetime.now(UTC) - timedelta(days=1),
            current_hash="hash",
            state="up_to_date",
            enabled=True,
            finding_counts={"phpstan_error": 2},
        )
    )
    await db_session.commit()

    await weekly_fleet_digest({})

    assert len(sent) == 1
    webhook_url, digest = sent[0]
    assert webhook_url == "https://example.com/webhook"
    assert (module.id, module.name) in digest.new_modules

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()
