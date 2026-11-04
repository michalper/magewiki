import os
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Module
from app.scanner.orchestrator import scan_repository
from tests.conftest import MAGENTO_FIXTURE_ENV, requires_magento_fixture


@requires_magento_fixture
@pytest.mark.slow
@pytest.mark.asyncio
async def test_real_magento_clone(db_session):
    repo_root = str(Path(os.environ[MAGENTO_FIXTURE_ENV]).resolve())

    result = await scan_repository(repo_root, db_session)
    assert result.modules_found >= 222

    store_module = await db_session.scalar(
        select(Module).where(Module.repo_root == repo_root, Module.name == "Magento_Store")
    )
    assert store_module is not None
    assert store_module.enabled is True

    ordo_module = await db_session.scalar(
        select(Module).where(Module.repo_root == repo_root, Module.name == "Ordo_Automation")
    )
    assert ordo_module is not None
    assert ordo_module.source_type == "vendor"
