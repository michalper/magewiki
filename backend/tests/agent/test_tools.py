import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete

from app.agent.tools import (
    find_by_class,
    find_by_event,
    get_dependencies,
    get_module,
    list_modules,
    read_file,
    search_modules,
)
from app.analyzer.prompts import MODULE_SYNTHESIS_PROMPT_VERSION
from app.models import AnalysisCache, Chunk, Module, ModuleDocument
from tests.conftest import scan_demo_store


def _vector(active: dict[int, float]) -> list[float]:
    v = [0.0] * 1536
    for i, val in active.items():
        v[i] = val
    return v


async def _make_bare_module(session, suffix: str, name: str | None = None) -> Module:
    module = Module(
        repo_root=f"/tmp/agent-tools-test-{suffix}",
        name=name or f"AgentToolsTestModule_{suffix}",
        path=".",
        source_type="standalone",
        state="up_to_date",
        enabled=True,
        current_hash=f"hash-{suffix}",
        last_scanned_at=datetime.now(UTC),
    )
    session.add(module)
    await session.flush()
    return module


@pytest.mark.asyncio
async def test_search_modules_wraps_hybrid_search(db_session, monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    module = await _make_bare_module(db_session, suffix)
    chunk = Chunk(
        module_id=module.id,
        chunk_type="file",
        relative_path="checkout.php",
        content_hash=f"chunk-{suffix}",
        text=f"blocks checkout when over credit limit {suffix}",
        embedding=_vector({0: 1.0}),
    )
    db_session.add(chunk)
    await db_session.commit()

    async def _fake_embed(q, **kwargs):
        return _vector({0: 1.0})

    monkeypatch.setattr("app.search.hybrid.embed_query_text", _fake_embed)

    result = await search_modules(db_session, query=f"credit limit {suffix}", limit=50)
    result_ids = {r["module_id"] for r in result["results"]}
    assert module.id in result_ids

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_get_module_not_found(db_session):
    result = await get_module(db_session, module_id=-1)
    assert result == {"found": False}


@pytest.mark.asyncio
async def test_get_module_unanalyzed_reports_status_and_dependencies(demo_store_path: Path, db_session):
    module = await scan_demo_store(demo_store_path, db_session)

    result = await get_module(db_session, module_id=module.id)

    assert result["found"] is True
    assert result["name"] == "Vendor_Module"
    assert result["analyzed"] is False
    assert result["dependencies"] == ["Magento_Sales"]
    assert result["state"] == module.state
    assert result["last_scanned_at"]


@pytest.mark.asyncio
async def test_get_module_analyzed_includes_doc_fields(demo_store_path: Path, db_session):
    module = await scan_demo_store(demo_store_path, db_session)

    # This fixture's content_hash is deterministic across runs — clear any leftover
    # cache row from a previous run of this same test before inserting a fresh one.
    await db_session.execute(delete(AnalysisCache).where(AnalysisCache.content_hash == module.current_hash))
    await db_session.commit()

    cache = AnalysisCache(
        content_hash=module.current_hash,
        model="seeded",
        prompt_version=MODULE_SYNTHESIS_PROMPT_VERSION,
        kind="module_synthesis",
        response={},
        tokens_in=0,
        tokens_out=0,
        cost_usd=Decimal(0),
    )
    db_session.add(cache)
    await db_session.flush()
    db_session.add(
        ModuleDocument(
            module_id=module.id,
            content_hash=module.current_hash,
            model="seeded",
            prompt_version=MODULE_SYNTHESIS_PROMPT_VERSION,
            cache_id=cache.id,
            doc={
                "summary": "Does things.",
                "description": "Does more things.",
                "features": [],
                "integrations": [],
                "tags": [{"name": "checkout", "source": "ai", "confidence": 0.9}],
                "pm_text": "Business text.",
                "dev_text": "Dev text.",
            },
        )
    )
    await db_session.commit()

    result = await get_module(db_session, module_id=module.id)

    assert result["analyzed"] is True
    assert result["summary"] == "Does things."
    assert result["pm_text"] == "Business text."
    assert result["dev_text"] == "Dev text."
    assert result["tags"] == [{"name": "checkout", "source": "ai", "confidence": 0.9}]


@pytest.mark.asyncio
async def test_get_dependencies_forward(demo_store_path: Path, db_session):
    module = await scan_demo_store(demo_store_path, db_session)

    result = await get_dependencies(db_session, module_id=module.id)

    assert result["found"] is True
    assert result["depends_on"] == ["Magento_Sales"]


@pytest.mark.asyncio
async def test_get_dependencies_used_by(db_session):
    suffix = uuid.uuid4().hex[:8]
    upstream = await _make_bare_module(db_session, f"{suffix}-up", name=f"Upstream_{suffix}")
    downstream = await _make_bare_module(db_session, f"{suffix}-down", name=f"Downstream_{suffix}")
    from app.models import ModuleDependency

    db_session.add(ModuleDependency(module_id=downstream.id, depends_on_name=upstream.name))
    await db_session.commit()

    result = await get_dependencies(db_session, module_id=upstream.id)

    assert result["used_by"] == [downstream.name]

    await db_session.execute(delete(Module).where(Module.id.in_([upstream.id, downstream.id])))
    await db_session.commit()


@pytest.mark.asyncio
async def test_find_by_event_matches_demo_store_observer(demo_store_path: Path, db_session):
    module = await scan_demo_store(demo_store_path, db_session)

    result = await find_by_event(db_session, event_name="sales_order_place_after")

    matches = [r for r in result["results"] if r["module_id"] == module.id]
    assert len(matches) == 1
    assert matches[0]["observer_class"] == "Vendor\\Module\\Observer\\SampleOrderObserver"


@pytest.mark.asyncio
async def test_find_by_class_covers_preference_and_plugin(demo_store_path: Path, db_session):
    module = await scan_demo_store(demo_store_path, db_session)

    plugin_result = await find_by_class(db_session, identifier="Address\\Total\\Collector")
    assert any(p["module_id"] == module.id for p in plugin_result["plugins_targeting_it"])

    override_result = await find_by_class(db_session, identifier="SampleInterface")
    assert any(p["module_id"] == module.id for p in override_result["overridden_by"])

    defined_result = await find_by_class(db_session, identifier="SampleCheckoutPlugin")
    assert any(c["module_id"] == module.id for c in defined_result["defined_in"])


@pytest.mark.asyncio
async def test_read_file_not_found_without_a_chunk(demo_store_path: Path, db_session):
    module = await scan_demo_store(demo_store_path, db_session)

    result = await read_file(db_session, module_id=module.id, relative_path="etc/module.xml")

    assert result == {"found": False}


@pytest.mark.asyncio
async def test_read_file_returns_stored_chunk_text(db_session):
    suffix = uuid.uuid4().hex[:8]
    module = await _make_bare_module(db_session, suffix)
    chunk = Chunk(
        module_id=module.id,
        chunk_type="file",
        relative_path="Plugin/SampleCheckoutPlugin.php",
        content_hash=f"chunk-{suffix}",
        text="Blocks checkout over the credit limit.",
        embedding=_vector({}),
    )
    db_session.add(chunk)
    await db_session.commit()

    result = await read_file(db_session, module_id=module.id, relative_path="Plugin/SampleCheckoutPlugin.php")

    assert result["found"] is True
    assert result["module_name"] == module.name
    assert result["chunks"] == [{"chunk_type": "file", "text": "Blocks checkout over the credit limit."}]

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_list_modules_filters_by_status_and_tags(db_session):
    suffix = uuid.uuid4().hex[:8]
    tagged = await _make_bare_module(db_session, f"{suffix}-tagged", name=f"Tagged_{suffix}")
    untagged = await _make_bare_module(db_session, f"{suffix}-untagged", name=f"Untagged_{suffix}")

    cache = AnalysisCache(
        content_hash=f"doc-{suffix}",
        model="seeded",
        prompt_version=MODULE_SYNTHESIS_PROMPT_VERSION,
        kind="module_synthesis",
        response={},
        tokens_in=0,
        tokens_out=0,
        cost_usd=Decimal(0),
    )
    db_session.add(cache)
    await db_session.flush()
    db_session.add(
        ModuleDocument(
            module_id=tagged.id,
            content_hash=f"doc-{suffix}",
            model="seeded",
            prompt_version=MODULE_SYNTHESIS_PROMPT_VERSION,
            cache_id=cache.id,
            doc={"tags": [{"name": "payments", "source": "ai", "confidence": 0.9}], "integrations": []},
        )
    )
    await db_session.commit()

    result = await list_modules(db_session, tags=["payments"], status="up_to_date")

    names = {m["name"] for m in result["modules"]}
    assert tagged.name in names
    assert untagged.name not in names

    await db_session.execute(delete(Module).where(Module.id.in_([tagged.id, untagged.id])))
    await db_session.commit()
