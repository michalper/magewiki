import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models import AnalysisCache, Module, ModuleDocument
from app.scanner.orchestrator import ScanAlreadyInProgressError


async def _make_module(session, suffix: str) -> Module:
    module = Module(
        repo_root=f"/tmp/module-detail-test-{suffix}",
        name=f"ModuleDetailTest_{suffix}",
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
async def test_get_module_returns_404_for_a_nonexistent_id():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/modules/999999999")

    assert response.status_code == 404
    assert response.json()["detail"] == "module not found"


@pytest.mark.asyncio
async def test_get_module_readme_returns_404_for_a_nonexistent_id():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/modules/999999999/readme")

    assert response.status_code == 404
    assert response.json()["detail"] == "module not found"


@pytest.mark.asyncio
async def test_get_module_readme_returns_404_when_not_yet_analyzed(db_session):
    suffix = uuid.uuid4().hex[:8]
    module = await _make_module(db_session, suffix)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/modules/{module.id}/readme")

    assert response.status_code == 404
    assert response.json()["detail"] == "module has not been analyzed yet"


@pytest.mark.asyncio
async def test_get_module_readme_renders_markdown_from_the_stored_doc(db_session):
    suffix = uuid.uuid4().hex[:8]
    module = await _make_module(db_session, suffix)

    cache = AnalysisCache(
        content_hash=module.current_hash,
        model="anthropic/claude-haiku-5-5",
        prompt_version="module_synthesis_v1",
        kind="module_synthesis",
        response={},
        tokens_in=100,
        tokens_out=50,
        cost_usd=Decimal("0.001"),
    )
    db_session.add(cache)
    await db_session.flush()

    doc = ModuleDocument(
        module_id=module.id,
        content_hash=module.current_hash,
        model="anthropic/claude-haiku-5-5",
        prompt_version="module_synthesis_v1",
        cache_id=cache.id,
        doc={
            "summary": "A test module.",
            "description": "Does testing things.",
            "features": [],
            "integrations": [],
            "tags": [],
            "config_options": [],
            "risks": [],
            "confidence": 0.9,
            "pm_text": "Business summary.",
            "dev_text": "Technical summary.",
            "rejected_tags": [],
        },
    )
    db_session.add(doc)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/modules/{module.id}/readme")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert f"# {module.name}" in response.text
    assert "A test module." in response.text
    assert "Business summary." in response.text


@pytest.mark.asyncio
async def test_scan_returns_409_when_already_in_progress(tmp_path, monkeypatch):
    async def _raise(repo_root, session):
        raise ScanAlreadyInProgressError(f"a scan of {repo_root} is already in progress")
        yield  # pragma: no cover - makes this an async generator function

    monkeypatch.setattr("app.scanner.orchestrator.scan_repository_events", _raise)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/scan", json={"path": str(tmp_path)})

    assert response.status_code == 409
    assert "already in progress" in response.json()["detail"]
