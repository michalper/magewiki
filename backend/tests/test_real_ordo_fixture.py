import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import DiPreference, Module, ModuleDependency, PhpClass, PhpClassMethod
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
    # composer.json's own "version" field wins over module.xml's setup_version
    # (which really is "0.1.0" in this real fixture, but is stale — see CLAUDE.md's
    # version-source-priority decision note).
    assert module.setup_version == "1.0.0"
    assert module.composer_name == "ordo/module-automation"
    assert module.license == ["MIT"]
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

    assert set(plugins.keys()) == set(EXPECTED_PLUGINS.keys())
    for fqcn, expected_method in EXPECTED_PLUGINS.items():
        method_names = {
            m.name for m in (await db_session.scalars(
                select(PhpClassMethod).where(PhpClassMethod.class_id == plugins[fqcn].id)
            )).all()
        }
        assert expected_method in method_names

    assert observers == EXPECTED_OBSERVERS

    preferences = (await db_session.scalars(
        select(DiPreference).where(DiPreference.module_id == module.id)
    )).all()
    assert len(preferences) > 0
