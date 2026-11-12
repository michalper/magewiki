"""Validates the e2e Playwright fixture (backend/tests/fixtures/conflict-store)
actually triggers every check_type it's designed for, at the much faster
pytest/real-DB layer -- before relying on it inside a full docker-compose +
Playwright run. Two synthetic modules, Vendor_ConflictA/Vendor_ConflictB,
deliberately collide on every fleet-wide conflict check plus the Phase 19
acl checks; ConflictA alone carries the missing_acl controller and the
Packagist-cache-backed external checks.
"""
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Module, ModuleQualityFinding
from app.scanner.orchestrator import scan_repository_events
from app.scanner.packagist_cache import set_cached

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
CONFLICT_STORE_PATH = FIXTURES_DIR / "conflict-store"

_FLEET_WIDE_CHECK_TYPES = {
    "plugin_conflict",
    "composer_conflict",
    "webapi_route_conflict",
    "db_schema_conflict",
    "circular_dependency",
    "preference_conflict",
    "cron_job_conflict",
    "graphql_field_conflict",
    "acl_resource_conflict",
}


@pytest.mark.asyncio
async def test_conflict_store_fixture_triggers_every_fleet_wide_check(db_session):
    repo_root = str(CONFLICT_STORE_PATH.resolve())

    await set_cached(
        db_session,
        "advisories:vendor/vulnerable-pkg",
        {
            "advisories": {
                "vendor/vulnerable-pkg": [
                    {
                        "cve": "CVE-2024-99999",
                        "title": "Fake test advisory",
                        "link": "https://example.com",
                        "affectedVersions": "<2.0",
                    }
                ]
            }
        },
    )
    await set_cached(
        db_session,
        "p2:vendor/abandoned-pkg",
        {"packages": {"vendor/abandoned-pkg": [{"version": "1.0.0", "abandoned": True}]}},
    )
    await set_cached(
        db_session,
        "p2:vendor/outdated-pkg",
        {"packages": {"vendor/outdated-pkg": [{"version": "2.0.0", "abandoned": False}]}},
    )
    # vendor/conflict-version-probe is a fake package (composer_conflict only)
    # -- seeded "clean" so neither security_advisory nor abandoned/outdated
    # ever depends on a real network call for it, matching global-setup.ts.
    await set_cached(
        db_session,
        "advisories:vendor/conflict-version-probe",
        {"advisories": {"vendor/conflict-version-probe": []}},
    )
    await set_cached(
        db_session,
        "p2:vendor/conflict-version-probe",
        {"packages": {"vendor/conflict-version-probe": [{"version": "6.5.0", "abandoned": False}]}},
    )
    await db_session.commit()

    async for _event in scan_repository_events(repo_root, db_session):
        pass

    module_a = await db_session.scalar(
        select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_ConflictA")
    )
    module_b = await db_session.scalar(
        select(Module).where(Module.repo_root == repo_root, Module.name == "Vendor_ConflictB")
    )
    assert module_a is not None
    assert module_b is not None

    check_types_a = {
        f.check_type
        for f in (
            await db_session.scalars(
                select(ModuleQualityFinding).where(ModuleQualityFinding.module_id == module_a.id)
            )
        ).all()
    }
    check_types_b = {
        f.check_type
        for f in (
            await db_session.scalars(
                select(ModuleQualityFinding).where(ModuleQualityFinding.module_id == module_b.id)
            )
        ).all()
    }

    missing_from_a = _FLEET_WIDE_CHECK_TYPES - check_types_a
    missing_from_b = _FLEET_WIDE_CHECK_TYPES - check_types_b
    assert not missing_from_a, f"Vendor_ConflictA missing: {missing_from_a}"
    assert not missing_from_b, f"Vendor_ConflictB missing: {missing_from_b}"

    # Single-module checks, ConflictA only.
    assert "missing_acl" in check_types_a
    assert "security_advisory" in check_types_a
    assert "abandoned_dependency" in check_types_a
    assert "outdated_dependency" in check_types_a
