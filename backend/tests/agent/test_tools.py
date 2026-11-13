import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, update

from app.agent.tools import (
    find_by_class,
    find_by_event,
    find_similar_modules,
    get_dependencies,
    get_module,
    get_module_findings,
    get_module_history,
    list_modules,
    read_file,
    search_modules,
)
from app.analyzer.prompts import MODULE_SYNTHESIS_PROMPT_VERSION
from app.models import (
    AnalysisCache,
    Chunk,
    Module,
    ModuleDocument,
    ModuleHistorySnapshot,
    ModuleQualityFinding,
)
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

    # Per-signal rank detail (retrieval-debugging) must survive the hybrid_search
    # -> tool-output boundary, not just the raw fused score.
    our_result = next(r for r in result["results"] if r["module_id"] == module.id)
    assert our_result["semantic_rank"] == 1
    assert "keyword_rank" in our_result
    assert "identifier_rank" in our_result

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_search_modules_reranks_when_enabled(db_session, monkeypatch):
    from app.config import settings
    from app.search.hybrid import SearchResult

    monkeypatch.setattr(settings, "rerank_enabled", True)

    candidates = [
        SearchResult(chunk_id=1, chunk_type="file", module_id=10, module_name="A", relative_path="a.php", text="a", score=0.9),
        SearchResult(chunk_id=2, chunk_type="file", module_id=20, module_name="B", relative_path="b.php", text="b", score=0.5),
    ]
    hybrid_calls: list[int] = []

    async def fake_hybrid_search(session, query, limit=10, **kwargs):
        hybrid_calls.append(limit)
        return candidates

    rerank_calls: list[list[int]] = []

    async def fake_rerank(session, query, results, *, top_k):
        rerank_calls.append([r.chunk_id for r in results])
        return list(reversed(results))[:top_k]  # deterministic, known transform

    monkeypatch.setattr("app.agent.tools.hybrid_search", fake_hybrid_search)
    monkeypatch.setattr("app.agent.tools.rerank_results", fake_rerank)

    result = await search_modules(db_session, query="anything", limit=1)

    # hybrid_search must be asked for more than the final `limit` -- a
    # reranker given only `limit` candidates has nothing left to reorder.
    assert hybrid_calls == [20]
    assert rerank_calls == [[1, 2]]
    # The final result must be the reranker's own output (reversed order,
    # trimmed to top_k), not hybrid_search's untouched top-1.
    assert result["results"] == [
        {
            "module_id": 20, "module_name": "B", "chunk_type": "file", "relative_path": "b.php",
            "text": "b", "score": 0.5, "semantic_rank": None, "keyword_rank": None, "identifier_rank": None,
        }
    ]


@pytest.mark.asyncio
async def test_search_modules_skips_reranking_when_disabled(db_session, monkeypatch):
    from app.config import settings

    suffix = uuid.uuid4().hex[:8]
    module = await _make_bare_module(db_session, suffix)
    chunk = Chunk(
        module_id=module.id, chunk_type="file", relative_path="a.php",
        content_hash=f"chunk-{suffix}", text=f"a match {suffix}", embedding=_vector({0: 1.0}),
    )
    db_session.add(chunk)
    await db_session.commit()

    async def _fake_embed(q, **kwargs):
        return _vector({0: 1.0})

    monkeypatch.setattr("app.search.hybrid.embed_query_text", _fake_embed)
    monkeypatch.setattr(settings, "rerank_enabled", False)

    called = False

    async def fake_rerank(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("rerank_results must not be called when rerank_enabled is False")

    monkeypatch.setattr("app.agent.tools.rerank_results", fake_rerank)

    result = await search_modules(db_session, query=f"match {suffix}", limit=5)

    assert called is False
    assert any(r["module_id"] == module.id for r in result["results"])

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_search_modules_rewrites_query_when_enabled(db_session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "query_rewrite_enabled", True)
    monkeypatch.setattr(settings, "rerank_enabled", False)

    rewrite_calls: list[str] = []

    async def fake_rewrite(session, query):
        rewrite_calls.append(query)
        return "rewritten query"

    hybrid_calls: list[str] = []

    async def fake_hybrid_search(session, query, limit=10, **kwargs):
        hybrid_calls.append(query)
        return []

    monkeypatch.setattr("app.agent.tools.rewrite_query", fake_rewrite)
    monkeypatch.setattr("app.agent.tools.hybrid_search", fake_hybrid_search)

    await search_modules(db_session, query="original query", limit=5)

    assert rewrite_calls == ["original query"]
    # hybrid_search must receive the rewrite's own output, not the original.
    assert hybrid_calls == ["rewritten query"]


@pytest.mark.asyncio
async def test_search_modules_skips_query_rewriting_when_disabled(db_session, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "query_rewrite_enabled", False)
    monkeypatch.setattr(settings, "rerank_enabled", False)

    called = False

    async def fake_rewrite(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("rewrite_query must not be called when query_rewrite_enabled is False")

    hybrid_calls: list[str] = []

    async def fake_hybrid_search(session, query, limit=10, **kwargs):
        hybrid_calls.append(query)
        return []

    monkeypatch.setattr("app.agent.tools.rewrite_query", fake_rewrite)
    monkeypatch.setattr("app.agent.tools.hybrid_search", fake_hybrid_search)

    await search_modules(db_session, query="original query", limit=5)

    assert called is False
    assert hybrid_calls == ["original query"]


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
async def test_get_dependencies_not_found(db_session):
    result = await get_dependencies(db_session, module_id=999999999)
    assert result == {"found": False}


def _base_dim(suffix: str) -> int:
    # Same per-test-unique-dimension reasoning as
    # tests/search/test_similar_modules.py's own helper: find_similar_modules
    # is fleet-wide and db_session never rolls back between tests, so a
    # fixed dimension would make this test's vectors collide with every
    # other similarity test's in the same pytest run.
    return int(suffix, 16) % 1500


@pytest.mark.asyncio
async def test_find_similar_modules_tool_returns_a_real_match(db_session):
    suffix = uuid.uuid4().hex[:8]
    base = _base_dim(suffix)
    target = await _make_bare_module(db_session, f"{suffix}-target", name=f"Target_{suffix}")
    close = await _make_bare_module(db_session, f"{suffix}-close", name=f"Close_{suffix}")

    db_session.add(
        Chunk(
            module_id=target.id,
            chunk_type="module",
            content_hash=f"module-chunk-{target.id}",
            text="module summary",
            embedding=_vector({base: 1.0}),
        )
    )
    db_session.add(
        Chunk(
            module_id=close.id,
            chunk_type="module",
            content_hash=f"module-chunk-{close.id}",
            text="module summary",
            embedding=_vector({base: 0.99, base + 1: 0.01}),
        )
    )
    await db_session.commit()

    result = await find_similar_modules(db_session, module_id=target.id)

    assert result["found"] is True
    assert result["module_name"] == target.name
    assert [s["module_id"] for s in result["similar"]] == [close.id]
    assert result["similar"][0]["similarity"] > 0.9

    await db_session.execute(delete(Module).where(Module.id.in_([target.id, close.id])))
    await db_session.commit()


@pytest.mark.asyncio
async def test_find_similar_modules_tool_not_found(db_session):
    result = await find_similar_modules(db_session, module_id=999999999)
    assert result == {"found": False}


@pytest.mark.asyncio
async def test_find_similar_modules_tool_empty_when_nothing_close_enough(db_session):
    suffix = uuid.uuid4().hex[:8]
    target = await _make_bare_module(db_session, f"{suffix}-target", name=f"Target_{suffix}")

    result = await find_similar_modules(db_session, module_id=target.id)

    assert result == {"found": True, "module_name": target.name, "similar": []}

    await db_session.execute(delete(Module).where(Module.id == target.id))
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


@pytest.mark.asyncio
async def test_list_modules_filters_by_enabled_and_integration(db_session):
    suffix = uuid.uuid4().hex[:8]
    enabled_module = await _make_bare_module(db_session, f"{suffix}-enabled", name=f"Enabled_{suffix}")
    disabled_module = await _make_bare_module(db_session, f"{suffix}-disabled", name=f"Disabled_{suffix}")
    await db_session.execute(update(Module).where(Module.id == disabled_module.id).values(enabled=False))

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
            module_id=enabled_module.id,
            content_hash=f"doc-{suffix}",
            model="seeded",
            prompt_version=MODULE_SYNTHESIS_PROMPT_VERSION,
            cache_id=cache.id,
            doc={"tags": [], "integrations": [{"name": "Klaviyo"}]},
        )
    )
    await db_session.commit()

    by_enabled = await list_modules(db_session, enabled=True)
    enabled_names = {m["name"] for m in by_enabled["modules"]}
    assert enabled_module.name in enabled_names
    assert disabled_module.name not in enabled_names

    by_integration = await list_modules(db_session, integration="klaviyo")
    integration_names = {m["name"] for m in by_integration["modules"]}
    assert enabled_module.name in integration_names
    assert disabled_module.name not in integration_names

    await db_session.execute(delete(Module).where(Module.id.in_([enabled_module.id, disabled_module.id])))
    await db_session.commit()


@pytest.mark.asyncio
async def test_list_modules_filters_by_check_type_and_reports_its_finding_count(db_session):
    suffix = uuid.uuid4().hex[:8]
    with_cve = await _make_bare_module(db_session, f"{suffix}-cve", name=f"WithCve_{suffix}")
    without_cve = await _make_bare_module(db_session, f"{suffix}-nocve", name=f"WithoutCve_{suffix}")

    db_session.add_all(
        [
            ModuleQualityFinding(
                module_id=with_cve.id,
                check_type="security_advisory",
                severity="blocking",
                file_path="composer.json",
                line=None,
                message="CVE-1",
            ),
            ModuleQualityFinding(
                module_id=with_cve.id,
                check_type="security_advisory",
                severity="blocking",
                file_path="composer.json",
                line=None,
                message="CVE-2",
            ),
            ModuleQualityFinding(
                module_id=without_cve.id,
                check_type="hardcoded_secret",
                severity="blocking",
                file_path="Foo.php",
                line=1,
                message="a secret",
            ),
        ]
    )
    await db_session.commit()

    result = await list_modules(db_session, check_type="security_advisory")

    names = {m["name"]: m for m in result["modules"]}
    assert with_cve.name in names
    assert without_cve.name not in names
    assert names[with_cve.name]["finding_count"] == 2

    no_filter = await list_modules(db_session, status="up_to_date", limit=1000)
    my_modules = [m for m in no_filter["modules"] if m["name"] in (with_cve.name, without_cve.name)]
    assert len(my_modules) == 2
    for m in my_modules:
        assert "finding_count" not in m

    await db_session.execute(delete(Module).where(Module.id.in_([with_cve.id, without_cve.id])))
    await db_session.commit()


@pytest.mark.asyncio
async def test_get_module_history_tool_returns_newest_first(db_session):
    suffix = uuid.uuid4().hex[:8]
    module = await _make_bare_module(db_session, suffix)
    older = ModuleHistorySnapshot(
        module_id=module.id,
        scanned_at=datetime(2026, 1, 1, tzinfo=UTC),
        current_hash="hash-a",
        state="up_to_date",
        enabled=True,
        finding_counts={"phpstan_error": 3},
    )
    newer = ModuleHistorySnapshot(
        module_id=module.id,
        scanned_at=datetime(2026, 2, 1, tzinfo=UTC),
        current_hash="hash-b",
        state="up_to_date",
        enabled=True,
        finding_counts={"phpstan_error": 1},
    )
    db_session.add_all([older, newer])
    await db_session.commit()

    result = await get_module_history(db_session, module_id=module.id)

    assert result["found"] is True
    assert result["module_name"] == module.name
    assert [entry["current_hash"] for entry in result["history"]] == ["hash-b", "hash-a"]
    assert result["history"][0]["finding_counts"] == {"phpstan_error": 1}

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_get_module_history_tool_not_found(db_session):
    result = await get_module_history(db_session, module_id=999999999)
    assert result == {"found": False}


@pytest.mark.asyncio
async def test_get_module_history_tool_empty_list_with_no_snapshots(db_session):
    suffix = uuid.uuid4().hex[:8]
    module = await _make_bare_module(db_session, suffix)
    await db_session.commit()

    result = await get_module_history(db_session, module_id=module.id)

    assert result == {"found": True, "module_name": module.name, "history": []}

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_get_module_findings_tool_returns_real_findings(db_session):
    suffix = uuid.uuid4().hex[:8]
    module = await _make_bare_module(db_session, suffix)
    db_session.add_all(
        [
            ModuleQualityFinding(
                module_id=module.id,
                check_type="hardcoded_secret",
                severity="blocking",
                file_path="Helper/Config.php",
                line=42,
                message="a secret",
            ),
            ModuleQualityFinding(
                module_id=module.id,
                check_type="license_risk",
                severity="warning",
                file_path="composer.json",
                line=None,
                message="GPL-3.0",
            ),
        ]
    )
    await db_session.commit()

    result = await get_module_findings(db_session, module_id=module.id)

    assert result["found"] is True
    assert result["module_name"] == module.name
    check_types = {f["check_type"] for f in result["findings"]}
    assert check_types == {"hardcoded_secret", "license_risk"}
    secret_finding = next(f for f in result["findings"] if f["check_type"] == "hardcoded_secret")
    assert secret_finding == {
        "check_type": "hardcoded_secret",
        "severity": "blocking",
        "file_path": "Helper/Config.php",
        "line": 42,
        "message": "a secret",
    }

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_get_module_findings_tool_filters_by_check_type(db_session):
    suffix = uuid.uuid4().hex[:8]
    module = await _make_bare_module(db_session, suffix)
    db_session.add_all(
        [
            ModuleQualityFinding(
                module_id=module.id,
                check_type="hardcoded_secret",
                severity="blocking",
                file_path="Helper/Config.php",
                line=42,
                message="a secret",
            ),
            ModuleQualityFinding(
                module_id=module.id,
                check_type="license_risk",
                severity="warning",
                file_path="composer.json",
                line=None,
                message="GPL-3.0",
            ),
        ]
    )
    await db_session.commit()

    result = await get_module_findings(db_session, module_id=module.id, check_type="license_risk")

    assert [f["check_type"] for f in result["findings"]] == ["license_risk"]

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()


@pytest.mark.asyncio
async def test_get_module_findings_tool_not_found(db_session):
    result = await get_module_findings(db_session, module_id=999999999)
    assert result == {"found": False}


@pytest.mark.asyncio
async def test_get_module_findings_tool_empty_list_with_no_findings(db_session):
    suffix = uuid.uuid4().hex[:8]
    module = await _make_bare_module(db_session, suffix)
    await db_session.commit()

    result = await get_module_findings(db_session, module_id=module.id)

    assert result == {"found": True, "module_name": module.name, "findings": []}

    await db_session.execute(delete(Module).where(Module.id == module.id))
    await db_session.commit()
