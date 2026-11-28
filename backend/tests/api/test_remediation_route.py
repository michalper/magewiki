import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.config import settings
from app.main import app
from app.models import Module, ModuleQualityFinding


async def _make_module_with_finding(session, suffix: str) -> tuple[Module, ModuleQualityFinding]:
    module = Module(
        repo_root=f"/tmp/remediation-route-test-{suffix}",
        name=f"RemediationRouteTestModule_{suffix}",
        path=".",
        source_type="standalone",
        state="up_to_date",
        current_hash=f"hash-{suffix}",
        last_scanned_at=datetime.now(UTC),
    )
    session.add(module)
    await session.flush()
    finding = ModuleQualityFinding(
        module_id=module.id,
        check_type="hardcoded_secret",
        severity="blocking",
        file_path="Model/Thing.php",
        line=12,
        message=f"An API key was found {suffix}",
    )
    session.add(finding)
    await session.commit()
    return module, finding


def _tool_response(remediation: str) -> SimpleNamespace:
    tool_call = SimpleNamespace(function=SimpleNamespace(arguments=json.dumps({"remediation": remediation})))
    message = SimpleNamespace(tool_calls=[tool_call])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=80, completion_tokens=40),
    )


@pytest.mark.asyncio
async def test_a_real_finding_returns_remediation_text(db_session, monkeypatch):
    monkeypatch.setattr(settings, "remediation_enabled", True)

    async def fake_acompletion(**kwargs):
        return _tool_response("Remove the hardcoded key.")

    monkeypatch.setattr("app.analyzer.client.litellm.acompletion", fake_acompletion)
    monkeypatch.setattr("app.analyzer.client.litellm.completion_cost", lambda **k: 0.0005)

    suffix = uuid.uuid4().hex[:8]
    module, finding = await _make_module_with_finding(db_session, suffix)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/modules/{module.id}/findings/remediation",
            json={
                "check_type": finding.check_type,
                "file_path": finding.file_path,
                "line": finding.line,
                "message": finding.message,
            },
        )

    assert response.status_code == 200
    assert response.json() == {"remediation": "Remove the hardcoded key."}

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_no_matching_finding_returns_404(db_session):
    suffix = uuid.uuid4().hex[:8]
    module, _finding = await _make_module_with_finding(db_session, suffix)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/modules/{module.id}/findings/remediation",
            json={"check_type": "hardcoded_secret", "file_path": "does/not/match.php", "line": 1, "message": "nope"},
        )

    assert response.status_code == 404

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_module_not_found_returns_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/modules/999999999/findings/remediation",
            json={"check_type": "hardcoded_secret", "file_path": "x.php", "line": 1, "message": "msg"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_feature_disabled_returns_403(db_session, monkeypatch):
    monkeypatch.setattr(settings, "remediation_enabled", False)

    suffix = uuid.uuid4().hex[:8]
    module, finding = await _make_module_with_finding(db_session, suffix)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/modules/{module.id}/findings/remediation",
            json={
                "check_type": finding.check_type,
                "file_path": finding.file_path,
                "line": finding.line,
                "message": finding.message,
            },
        )

    assert response.status_code == 403

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_budget_exceeded_returns_503(db_session, monkeypatch):
    monkeypatch.setattr(settings, "remediation_enabled", True)
    monkeypatch.setattr(settings, "llm_monthly_budget_usd", -1.0)

    suffix = uuid.uuid4().hex[:8]
    module, finding = await _make_module_with_finding(db_session, suffix)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/modules/{module.id}/findings/remediation",
            json={
                "check_type": finding.check_type,
                "file_path": finding.file_path,
                "line": finding.line,
                "message": finding.message,
            },
        )

    assert response.status_code == 503

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()
