import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, update

from app.main import app
from app.models import AnalysisCache, Module, ModuleDocument, ModuleQualityFinding, PhpClass


async def _make_module(
    db_session,
    suffix: str,
    *,
    name: str | None = None,
    source_type: str = "standalone",
    state: str = "up_to_date",
    enabled: bool | None = True,
    repo_root: str | None = None,
    last_scanned_at: datetime | None = None,
) -> Module:
    module = Module(
        repo_root=repo_root or f"/tmp/modules-list-test-{suffix}",
        name=name or f"ModulesListTest_{suffix}",
        path=".",
        source_type=source_type,
        state=state,
        enabled=enabled,
        current_hash=f"hash-{suffix}",
        last_scanned_at=last_scanned_at or datetime.now(UTC),
    )
    db_session.add(module)
    await db_session.flush()
    return module


async def _add_doc(db_session, module: Module, suffix: str) -> None:
    cache = AnalysisCache(
        content_hash=f"doc-{suffix}",
        model="seeded",
        prompt_version="v1",
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
            content_hash=f"doc-{suffix}",
            model="seeded",
            prompt_version="v1",
            cache_id=cache.id,
            doc={"tags": [], "integrations": []},
        )
    )
    await db_session.commit()


async def _cleanup(db_session, *modules: Module) -> None:
    await db_session.execute(delete(Module).where(Module.id.in_([m.id for m in modules])))
    await db_session.commit()


def _order_by_top_level_keys(statement: str) -> list[str]:
    """The real ORDER BY sort keys, as top-level comma-separated terms --
    NOT a plain substring search. A naive `"modules.id" in order_by_clause`
    check is a false positive here: class_count/plugin_count/observer_count
    sort columns are themselves correlated subqueries
    (`... WHERE php_classes.module_id = modules.id`), so "modules.id" shows
    up inside the ORDER BY clause's text regardless of whether Module.id is
    actually a sort key -- confirmed by hand, this exact test passed even
    with the real tiebreaker reverted until the check was made paren-depth
    aware.
    """
    order_by_clause = re.split(r"\bLIMIT\b", statement.split("ORDER BY", 1)[1])[0]
    keys, depth, current = [], 0, ""
    for char in order_by_clause:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            keys.append(current.strip())
            current = ""
        else:
            current += char
    keys.append(current.strip())
    return keys


@pytest.mark.asyncio
async def test_list_modules_returns_every_matching_module_by_default(db_session):
    suffix = uuid.uuid4().hex[:8]
    a = await _make_module(db_session, f"{suffix}-a", name=f"A_{suffix}")
    b = await _make_module(db_session, f"{suffix}-b", name=f"B_{suffix}")
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/modules", params={"search": suffix})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    names = {m["name"] for m in body["modules"]}
    assert names == {a.name, b.name}

    await _cleanup(db_session, a, b)


@pytest.mark.asyncio
async def test_list_modules_search_matches_name_or_composer_name(db_session):
    token = uuid.uuid4().hex[:8]  # the actual search term
    scope = uuid.uuid4().hex[:8]  # only for repo_root/hash uniqueness, deliberately NOT part of the search
    by_name = await _make_module(db_session, f"{scope}-byname", name=f"FindMe_{token}")
    by_composer_name = await _make_module(db_session, f"{scope}-bycomposer", name=f"Unrelated_{scope}")
    await db_session.execute(
        update(Module).where(Module.id == by_composer_name.id).values(composer_name=f"vendor/pkg-{token}")
    )
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/modules", params={"search": token})

    # by_name matches on Module.name; by_composer_name's *name* doesn't
    # contain `token` at all, only its composer_name does -- proving the
    # search spans both columns, not just Module.name.
    names = {m["name"] for m in response.json()["modules"]}
    assert names == {by_name.name, by_composer_name.name}

    await _cleanup(db_session, by_name, by_composer_name)


@pytest.mark.asyncio
async def test_list_modules_filters_by_source_type_state_and_repo_root(db_session):
    suffix = uuid.uuid4().hex[:8]
    repo_root = f"/tmp/modules-list-filter-{suffix}"
    app_code = await _make_module(
        db_session, f"{suffix}-appcode", source_type="app_code", state="up_to_date", repo_root=repo_root
    )
    vendor = await _make_module(
        db_session, f"{suffix}-vendor", source_type="vendor", state="pending", repo_root=repo_root
    )
    elsewhere = await _make_module(db_session, f"{suffix}-elsewhere", source_type="app_code", state="up_to_date")
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        by_source = await client.get("/modules", params={"repo_root": repo_root, "source_type": "app_code"})
        by_state = await client.get("/modules", params={"repo_root": repo_root, "state": "pending"})
        by_repo = await client.get("/modules", params={"repo_root": repo_root})

    assert {m["name"] for m in by_source.json()["modules"]} == {app_code.name}
    assert {m["name"] for m in by_state.json()["modules"]} == {vendor.name}
    assert {m["name"] for m in by_repo.json()["modules"]} == {app_code.name, vendor.name}
    assert elsewhere.name not in {m["name"] for m in by_repo.json()["modules"]}

    await _cleanup(db_session, app_code, vendor, elsewhere)


@pytest.mark.asyncio
async def test_list_modules_filters_by_enabled_true_false_and_unknown(db_session):
    suffix = uuid.uuid4().hex[:8]
    on = await _make_module(db_session, f"{suffix}-on", enabled=True)
    off = await _make_module(db_session, f"{suffix}-off", enabled=False)
    unknown = await _make_module(db_session, f"{suffix}-unknown", enabled=None)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        true_resp = await client.get("/modules", params={"search": suffix, "enabled": "true"})
        false_resp = await client.get("/modules", params={"search": suffix, "enabled": "false"})
        unknown_resp = await client.get("/modules", params={"search": suffix, "enabled": "unknown"})

    assert {m["name"] for m in true_resp.json()["modules"]} == {on.name}
    assert {m["name"] for m in false_resp.json()["modules"]} == {off.name}
    assert {m["name"] for m in unknown_resp.json()["modules"]} == {unknown.name}

    await _cleanup(db_session, on, off, unknown)


@pytest.mark.asyncio
async def test_list_modules_filters_by_has_doc(db_session):
    suffix = uuid.uuid4().hex[:8]
    with_doc = await _make_module(db_session, f"{suffix}-doc")
    without_doc = await _make_module(db_session, f"{suffix}-nodoc")
    await _add_doc(db_session, with_doc, suffix)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        has_doc = await client.get("/modules", params={"search": suffix, "has_doc": "true"})
        no_doc = await client.get("/modules", params={"search": suffix, "has_doc": "false"})

    assert {m["name"] for m in has_doc.json()["modules"]} == {with_doc.name}
    assert {m["name"] for m in no_doc.json()["modules"]} == {without_doc.name}

    await _cleanup(db_session, with_doc, without_doc)


@pytest.mark.asyncio
async def test_list_modules_filters_by_finding_check_type_and_reports_scoped_counts(db_session):
    """Also a regression test for scoping _quality_finding_counts_by_module to
    the returned page: each module's own finding_counts must still be correct
    even though the lookup is no longer whole-DB."""
    suffix = uuid.uuid4().hex[:8]
    with_secret = await _make_module(db_session, f"{suffix}-secret")
    with_cve = await _make_module(db_session, f"{suffix}-cve")
    clean = await _make_module(db_session, f"{suffix}-clean")
    db_session.add_all(
        [
            ModuleQualityFinding(
                module_id=with_secret.id, check_type="hardcoded_secret", severity="blocking", message="m"
            ),
            ModuleQualityFinding(
                module_id=with_secret.id, check_type="hardcoded_secret", severity="blocking", message="m2"
            ),
            ModuleQualityFinding(
                module_id=with_cve.id, check_type="security_advisory", severity="blocking", message="m"
            ),
        ]
    )
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/modules", params={"search": suffix, "finding": "hardcoded_secret"}
        )

    body = response.json()
    assert {m["name"] for m in body["modules"]} == {with_secret.name}
    assert body["modules"][0]["finding_counts"] == {"hardcoded_secret": 2}

    await _cleanup(db_session, with_secret, with_cve, clean)


@pytest.mark.asyncio
async def test_list_modules_sorts_by_class_count_and_last_scanned_at(db_session):
    suffix = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)
    older = await _make_module(db_session, f"{suffix}-older", name=f"Z_{suffix}", last_scanned_at=now - timedelta(days=1))
    newer = await _make_module(db_session, f"{suffix}-newer", name=f"A_{suffix}", last_scanned_at=now)
    db_session.add(PhpClass(module_id=newer.id, fqcn="X\\Y", class_name="Y", kind="class", file_path="Y.php"))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        by_class_count_desc = await client.get(
            "/modules", params={"search": suffix, "sort_by": "class_count", "sort_dir": "desc"}
        )
        by_last_scanned_asc = await client.get(
            "/modules", params={"search": suffix, "sort_by": "last_scanned_at", "sort_dir": "asc"}
        )

    assert [m["name"] for m in by_class_count_desc.json()["modules"]] == [newer.name, older.name]
    assert [m["name"] for m in by_last_scanned_asc.json()["modules"]] == [older.name, newer.name]

    await _cleanup(db_session, older, newer)


@pytest.mark.asyncio
async def test_list_modules_order_by_includes_module_id_tiebreaker(db_session):
    """White-box regression test: Postgres doesn't *guarantee* a stable order
    among ties across separate LIMIT/OFFSET queries without an explicit
    tiebreaker, but confirmed by hand that it also doesn't reliably show the
    instability either -- a tiny, unmodified table with no concurrent writes
    gets a consistent plan/scan order run to run regardless, so asserting on
    *observed* row order (as the test below this one does) can pass whether or
    not the tiebreaker is actually there. Assert on the real, executed SQL's
    ORDER BY clause instead -- the one thing this can actually prove.
    """
    from sqlalchemy import event

    from app.db import engine as db_engine

    captured: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        if "FROM modules" in statement and "ORDER BY" in statement:
            captured.append(statement)

    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.get(
                "/modules", params={"sort_by": "plugin_count", "sort_dir": "asc", "limit": 5, "offset": 0}
            )
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)

    assert captured, "expected a SELECT ... FROM modules ... ORDER BY statement to run"
    assert _order_by_top_level_keys(captured[-1])[-1] == "modules.id"


@pytest.mark.asyncio
async def test_list_modules_breaks_sort_ties_deterministically_across_pages(db_session):
    # Three modules tied on every sortable column (last_scanned_at equal,
    # class/plugin/observer_count all 0). This is a behavioral sanity check
    # (pagination doesn't crash/duplicate/skip on a static table) -- the real,
    # reliable proof that the Module.id tiebreaker is actually in the query is
    # the white-box SQL-inspection test above; see its own docstring for why.
    suffix = uuid.uuid4().hex[:8]
    tie = datetime.now(UTC)
    first = await _make_module(db_session, f"{suffix}-1", name=f"Tie_{suffix}_1", last_scanned_at=tie)
    second = await _make_module(db_session, f"{suffix}-2", name=f"Tie_{suffix}_2", last_scanned_at=tie)
    third = await _make_module(db_session, f"{suffix}-3", name=f"Tie_{suffix}_3", last_scanned_at=tie)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        pages = [
            await client.get(
                "/modules",
                params={"search": suffix, "sort_by": "last_scanned_at", "sort_dir": "asc", "limit": 1, "offset": offset},
            )
            for offset in range(3)
        ]

    names_by_offset = [page.json()["modules"][0]["name"] for page in pages]
    assert first.id < second.id < third.id  # sequential flushes -> ascending ids
    assert names_by_offset == [first.name, second.name, third.name]
    assert len(set(names_by_offset)) == 3  # no duplicate across pages, nothing skipped

    await _cleanup(db_session, first, second, third)


@pytest.mark.asyncio
async def test_list_modules_prioritize_doc_floats_doc_modules_above_the_chosen_sort(db_session):
    suffix = uuid.uuid4().hex[:8]
    # Named so plain alphabetical (sort_by=name) would put the undoc'd module
    # first -- prioritize_doc must override that regardless.
    undocumented_but_alphabetically_first = await _make_module(db_session, f"{suffix}-a", name=f"A_{suffix}")
    documented = await _make_module(db_session, f"{suffix}-z", name=f"Z_{suffix}")
    await _add_doc(db_session, documented, suffix)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        prioritized = await client.get(
            "/modules", params={"search": suffix, "sort_by": "name", "prioritize_doc": "true"}
        )
        not_prioritized = await client.get(
            "/modules", params={"search": suffix, "sort_by": "name", "prioritize_doc": "false"}
        )

    assert [m["name"] for m in prioritized.json()["modules"]] == [documented.name, undocumented_but_alphabetically_first.name]
    assert [m["name"] for m in not_prioritized.json()["modules"]] == [undocumented_but_alphabetically_first.name, documented.name]

    await _cleanup(db_session, undocumented_but_alphabetically_first, documented)


@pytest.mark.asyncio
async def test_list_modules_paginates_with_limit_and_offset_and_reports_the_real_total(db_session):
    suffix = uuid.uuid4().hex[:8]
    modules = [
        await _make_module(db_session, f"{suffix}-{i}", name=f"Page_{suffix}_{i:02d}") for i in range(5)
    ]
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first_page = await client.get("/modules", params={"search": suffix, "limit": 2, "offset": 0})
        second_page = await client.get("/modules", params={"search": suffix, "limit": 2, "offset": 2})

    assert first_page.json()["total"] == 5
    assert [m["name"] for m in first_page.json()["modules"]] == [f"Page_{suffix}_00", f"Page_{suffix}_01"]
    assert second_page.json()["total"] == 5
    assert [m["name"] for m in second_page.json()["modules"]] == [f"Page_{suffix}_02", f"Page_{suffix}_03"]

    await _cleanup(db_session, *modules)


@pytest.mark.asyncio
async def test_list_modules_rejects_an_invalid_sort_by_or_enabled_value():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        bad_sort = await client.get("/modules", params={"sort_by": "not_a_real_column"})
        bad_enabled = await client.get("/modules", params={"enabled": "maybe"})

    assert bad_sort.status_code == 422
    assert bad_enabled.status_code == 422
