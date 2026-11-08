import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import (
    DiPreference,
    Module,
    ModuleDependency,
    ModuleQualityFinding,
    PhpClass,
    PhpClassMethod,
)
from app.scanner.orchestrator import scan_repository
from tests.conftest import ORDO_FIXTURE_ENV, requires_ordo_fixture

EXPECTED_PLUGINS = {
    "Ordo\\Automation\\Plugin\\Quote\\BlockOverLimitCheckout": "beforePlaceOrder",
    "Ordo\\Automation\\Plugin\\Email\\EmailMessageMessageIdPlugin": "afterCreate",
    "Ordo\\Automation\\Plugin\\SalesRule\\SimpleActionOptionsProviderPlugin": "afterToOptionArray",
}

EXPECTED_OBSERVERS = {
    "EvaluateCustomerScoreRules",
    "TrimExcessFreeGifts",
    "RecordTriggerOutcome",
    "DispatchScoreThresholdCampaigns",
    "DispatchVisitorTagAddedCampaigns",
    "StitchVisitorIdentity",
    "DispatchCustomerRegisteredCampaigns",
    "DispatchOrderPlacedCampaigns",
    "SendWelcomeEmail",
    "DispatchTagAddedCampaigns",
    "HoldOrderForApproval",
}


@requires_ordo_fixture
@pytest.mark.asyncio
async def test_real_ordo_automation_module(db_session):
    repo_root = str(Path(os.environ[ORDO_FIXTURE_ENV]).resolve())

    result = await scan_repository(repo_root, db_session)
    assert result.modules_found == 1

    module = await db_session.scalar(
        select(Module).where(Module.repo_root == repo_root, Module.name == "Ordo_Automation")
    )
    assert module is not None
    # Both module.xml's setup_version and composer.json's own "version" field
    # were deliberately dropped upstream (see CLAUDE.md's version-source-
    # priority decision note's follow-up) — None is the honest answer now,
    # not a stale guess from either source.
    assert module.setup_version is None
    assert module.composer_name == "michalper/ordo"
    assert module.license == ["OSL-3.0"]
    assert module.homepage == "https://ordo.marketing"
    assert module.enabled is None  # no app/etc/config.php at the standalone module's own root

    deps = (await db_session.scalars(
        select(ModuleDependency).where(ModuleDependency.module_id == module.id)
    )).all()
    assert {d.depends_on_name for d in deps} == {
        "Magento_Sales", "Magento_Quote", "Magento_Customer", "Magento_Email", "Magento_SalesRule",
    }

    classes = (await db_session.scalars(select(PhpClass).where(PhpClass.module_id == module.id))).all()
    plugins = {c.fqcn: c for c in classes if c.is_plugin}
    observers = {c.class_name for c in classes if c.is_observer}

    # Subset, not exact equality: this is a real, actively-developed module
    # (confirmed: a routine `git pull` here once added 780 files) — pinning
    # every plugin/observer that happens to exist today would make this test
    # fail on every unrelated upstream change. EXPECTED_PLUGINS/_OBSERVERS are
    # a stable, known-present sample that verifies the scanner still finds
    # real di.xml plugins/events.xml observers correctly, not an exhaustive
    # inventory of the module's current state.
    assert EXPECTED_PLUGINS.keys() <= plugins.keys()
    for fqcn, expected_method in EXPECTED_PLUGINS.items():
        method_names = {
            m.name for m in (await db_session.scalars(
                select(PhpClassMethod).where(PhpClassMethod.class_id == plugins[fqcn].id)
            )).all()
        }
        assert expected_method in method_names

    assert EXPECTED_OBSERVERS <= observers

    preferences = (await db_session.scalars(
        select(DiPreference).where(DiPreference.module_id == module.id)
    )).all()
    assert len(preferences) > 0


@requires_ordo_fixture
@pytest.mark.asyncio
async def test_real_ordo_automation_phpunit_execution(db_session):
    """Real end-to-end verification of check_php_unit_tests against Ordo
    Automation's own real, non-mocked Test/Unit suite (the module ships its
    own standalone-runnable vendor/bin/phpunit + phpunit.xml.dist — see
    CLAUDE.md's "Real PHPUnit test execution" decision note) — not a
    synthetic fixture, since getting a real module's own standalone PHPUnit
    bootstrap wired up correctly can't be faked with a toy Test/Unit
    directory the way every other check in this project could be.
    """
    repo_root = str(Path(os.environ[ORDO_FIXTURE_ENV]).resolve())

    await scan_repository(repo_root, db_session)

    module = await db_session.scalar(
        select(Module).where(Module.repo_root == repo_root, Module.name == "Ordo_Automation")
    )
    assert module is not None
    assert module.phpunit_tests_run is not None
    # A real, actively-developed module with thousands of real unit tests --
    # not a toy count, and not asserting an exact number (it grows over
    # time, same reasoning EXPECTED_PLUGINS/_OBSERVERS above already use).
    assert module.phpunit_tests_run > 1000
    assert module.phpunit_coverage_percent is not None
    assert module.phpunit_coverage_percent > 50.0

    findings = (
        await db_session.scalars(
            select(ModuleQualityFinding).where(
                ModuleQualityFinding.module_id == module.id,
                ModuleQualityFinding.check_type == "phpunit_failure",
            )
        )
    ).all()
    # Confirmed real, reproducible, and expected -- NOT a bug in this check:
    # PushEndpointValidatorTest::testAllowsAPublicHttpsHostname does a real
    # DNS lookup to verify SSRF-guard logic ("does this hostname resolve to
    # a public, non-private IP"), which genuinely can't succeed in this
    # sidecar's own container (php_analyzer_net is `internal: true` -- see
    # docker-compose.yml and CLAUDE.md's "Real PHPUnit test execution"
    # decision note). Accepted as the cost of real network isolation for a
    # sandbox that executes arbitrary third-party test code, same as
    # Test/Integration/Test/Api being out of scope entirely -- a known,
    # understood limitation, not swallowed silently: asserting the EXACT
    # known failure here means a real regression (a different test newly
    # failing) still fails this test loudly instead of being masked by a
    # loose "at most N failures" bound.
    assert len(findings) == 1
    assert "PushEndpointValidatorTest" in findings[0].message
