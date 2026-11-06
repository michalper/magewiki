import uuid
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.db import async_session_factory
from app.main import app
from app.models import Module, ModuleQualityFinding


@pytest.fixture
async def repos_fixture(db_session):
    suffix = uuid.uuid4().hex[:8]
    repo_a = f"/tmp/repo-a-{suffix}"
    repo_b = f"/tmp/repo-b-{suffix}"

    module_a1 = Module(
        repo_root=repo_a,
        name=f"ModuleA1_{suffix}",
        path=".",
        source_type="standalone",
        state="up_to_date",
        current_hash="h1",
        enabled=True,
        has_readme=True,
        has_tests=False,
        last_scanned_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    module_a2 = Module(
        repo_root=repo_a,
        name=f"ModuleA2_{suffix}",
        path=".",
        source_type="standalone",
        state="up_to_date",
        current_hash="h2",
        enabled=False,
        has_readme=False,
        has_tests=False,
        last_scanned_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    module_b1 = Module(
        repo_root=repo_b,
        name=f"ModuleB1_{suffix}",
        path=".",
        source_type="standalone",
        state="up_to_date",
        current_hash="h3",
        enabled=True,
        has_readme=True,
        has_tests=True,
        last_scanned_at=datetime(2026, 1, 3, tzinfo=UTC),
    )
    db_session.add_all([module_a1, module_a2, module_b1])
    await db_session.flush()

    db_session.add_all(
        [
            ModuleQualityFinding(
                module_id=module_a1.id,
                check_type="hardcoded_secret",
                severity="blocking",
                file_path="Foo.php",
                line=1,
                message="secret",
            ),
            ModuleQualityFinding(
                module_id=module_a2.id,
                check_type="composer_completeness",
                severity="warning",
                file_path="composer.json",
                line=None,
                message="missing name",
            ),
        ]
    )
    await db_session.commit()

    yield repo_a, repo_b, [module_a1, module_a2, module_b1]

    all_ids = [module_a1.id, module_a2.id, module_b1.id]
    async with async_session_factory() as cleanup_session:
        await cleanup_session.execute(delete(Module).where(Module.id.in_(all_ids)))
        await cleanup_session.commit()


@pytest.mark.asyncio
async def test_list_repos_aggregates_health_per_repo(repos_fixture):
    repo_a, repo_b, _modules = repos_fixture

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/repos")

    assert response.status_code == 200
    by_repo = {r["repo_root"]: r for r in response.json()}

    assert repo_a in by_repo
    assert repo_b in by_repo

    a = by_repo[repo_a]
    assert a["module_count"] == 2
    assert a["enabled_count"] == 1
    assert a["has_readme_count"] == 1
    assert a["has_tests_count"] == 0
    assert a["secrets_count"] == 1
    assert a["composer_issue_count"] == 1
    assert a["last_scanned_at"].startswith("2026-01-02")

    b = by_repo[repo_b]
    assert b["module_count"] == 1
    assert b["enabled_count"] == 1
    assert b["has_readme_count"] == 1
    assert b["has_tests_count"] == 1
    assert b["secrets_count"] == 0
