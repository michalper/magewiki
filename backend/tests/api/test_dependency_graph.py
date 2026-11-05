import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db import async_session_factory
from app.main import app
from app.models import DiPlugin, DiPreference, Module, ModuleDependency, PhpClass


async def _make_module(session, suffix: str, name: str) -> Module:
    module = Module(
        repo_root=f"/tmp/graph-test-{suffix}",
        name=name,
        path=".",
        source_type="standalone",
        state="up_to_date",
        current_hash=f"hash-{suffix}",
        last_scanned_at=datetime.now(UTC),
    )
    session.add(module)
    await session.flush()
    return module


def _make_php_class(module_id: int, fqcn: str) -> PhpClass:
    return PhpClass(
        module_id=module_id,
        fqcn=fqcn,
        namespace=fqcn.rsplit("\\", 1)[0],
        class_name=fqcn.rsplit("\\", 1)[1],
        kind="class",
        file_path="dummy.php",
        is_plugin=False,
        is_observer=False,
    )


@pytest.fixture
async def graph_fixture(db_session):
    suffix = uuid.uuid4().hex[:8]
    center = await _make_module(db_session, suffix, f"Center_{suffix}")
    dep_target = await _make_module(db_session, f"{suffix}-a", f"DepTarget_{suffix}")
    dep_source = await _make_module(db_session, f"{suffix}-b", f"DepSource_{suffix}")
    override_target = await _make_module(db_session, f"{suffix}-c", f"OverrideTarget_{suffix}")
    override_source = await _make_module(db_session, f"{suffix}-d", f"OverrideSource_{suffix}")
    plugin_target = await _make_module(db_session, f"{suffix}-e", f"PluginTarget_{suffix}")
    plugin_source = await _make_module(db_session, f"{suffix}-f", f"PluginSource_{suffix}")

    center_fqcn = f"Center{suffix}\\CenterClass"
    override_target_fqcn = f"OverrideTarget{suffix}\\Foo"
    plugin_target_fqcn = f"PluginTarget{suffix}\\Bar"
    unresolved_fqcn = f"Unresolved{suffix}\\Interface"

    db_session.add_all(
        [
            _make_php_class(center.id, center_fqcn),
            _make_php_class(override_target.id, override_target_fqcn),
            _make_php_class(plugin_target.id, plugin_target_fqcn),
            ModuleDependency(module_id=center.id, depends_on_name=dep_target.name),
            ModuleDependency(module_id=dep_source.id, depends_on_name=center.name),
            DiPreference(module_id=center.id, for_type=override_target_fqcn, preference_type="x"),
            DiPreference(module_id=center.id, for_type=unresolved_fqcn, preference_type="x"),
            DiPreference(module_id=override_source.id, for_type=center_fqcn, preference_type="x"),
            DiPlugin(module_id=center.id, intercepted_type=plugin_target_fqcn, plugin_name="p", plugin_class="x"),
            DiPlugin(module_id=plugin_source.id, intercepted_type=center_fqcn, plugin_name="p", plugin_class="x"),
        ]
    )
    await db_session.commit()

    modules = {
        "center": center,
        "dep_target": dep_target,
        "dep_source": dep_source,
        "override_target": override_target,
        "override_source": override_source,
        "plugin_target": plugin_target,
        "plugin_source": plugin_source,
    }
    yield modules, unresolved_fqcn

    all_ids = [m.id for m in modules.values()]
    async with async_session_factory() as cleanup_session:
        await cleanup_session.execute(delete(Module).where(Module.id.in_(all_ids)))
        await cleanup_session.commit()


@pytest.mark.asyncio
async def test_graph_includes_all_relation_directions(graph_fixture):
    modules, unresolved_fqcn = graph_fixture
    center = modules["center"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/modules/{center.id}/graph")

    assert response.status_code == 200
    body = response.json()
    assert body["center_module_id"] == center.id
    assert body["center_label"] == center.name

    node_by_id = {n["id"]: n for n in body["nodes"]}
    for key in ("dep_target", "dep_source", "override_target", "override_source", "plugin_target", "plugin_source"):
        node_id = f"module:{modules[key].id}"
        assert node_id in node_by_id
        assert node_by_id[node_id]["kind"] == "module"

    external_id = f"ext:{unresolved_fqcn}"
    assert external_id in node_by_id
    assert node_by_id[external_id]["kind"] == "external"
    assert node_by_id[external_id]["module_id"] is None

    edges = {(e["source"], e["target"], e["relation"]) for e in body["edges"]}
    center_id = f"module:{center.id}"
    assert (center_id, f"module:{modules['dep_target'].id}", "depends_on") in edges
    assert (f"module:{modules['dep_source'].id}", center_id, "depends_on") in edges
    assert (center_id, f"module:{modules['override_target'].id}", "overrides") in edges
    assert (f"module:{modules['override_source'].id}", center_id, "overrides") in edges
    assert (center_id, f"module:{modules['plugin_target'].id}", "plugins") in edges
    assert (f"module:{modules['plugin_source'].id}", center_id, "plugins") in edges
    assert (center_id, external_id, "overrides") in edges


@pytest.mark.asyncio
async def test_graph_dedupes_nodes_but_not_edges(graph_fixture, db_session):
    modules, _ = graph_fixture
    center = modules["center"]
    plugin_target = modules["plugin_target"]

    # A second class owned by the same plugin_target module, also plugged by center —
    # should add a second "plugins" edge without duplicating the plugin_target node.
    second_fqcn = f"{plugin_target.name}\\Baz"
    db_session.add(_make_php_class(plugin_target.id, second_fqcn))
    db_session.add(
        DiPlugin(module_id=center.id, intercepted_type=second_fqcn, plugin_name="p2", plugin_class="x")
    )
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/modules/{center.id}/graph")

    body = response.json()
    plugin_target_node_ids = [n["id"] for n in body["nodes"] if n["id"] == f"module:{plugin_target.id}"]
    assert len(plugin_target_node_ids) == 1  # deduped

    plugin_edges = [
        e for e in body["edges"] if e["target"] == f"module:{plugin_target.id}" and e["relation"] == "plugins"
    ]
    assert len(plugin_edges) == 2  # not deduped


@pytest.mark.asyncio
async def test_graph_404_for_unknown_module():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/modules/999999999/graph")

    assert response.status_code == 404
