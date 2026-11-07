from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

router = APIRouter()

# backend/app/api/routes/health.py -> backend/alembic.ini
_ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"

# Read once at import time: the code's own migration files never change while
# this process is running, so there's no reason to touch the filesystem on
# every request.
_CODE_REVISION = ScriptDirectory.from_config(Config(str(_ALEMBIC_INI))).get_current_head()


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    try:
        await session.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:  # noqa: BLE001 - health check must never crash, just report degraded
        db_status = "error"

    # Catches the real incident this closes: a container started against a DB
    # whose schema is behind the running code (e.g. migrations were skipped,
    # or an old container is pointed at a newly-migrated DB) -- without this,
    # that surfaces only as a cryptic "column ... does not exist" 500 on the
    # first real query, reported to users as a generic "Cannot load modules."
    db_revision: str | None = None
    schema_status = "unknown"
    if db_status == "ok":
        try:
            result = await session.execute(text("SELECT version_num FROM alembic_version"))
            db_revision = result.scalar_one_or_none()
            schema_status = "ok" if db_revision == _CODE_REVISION else "stale"
        except Exception:  # noqa: BLE001 - e.g. alembic_version doesn't exist yet
            schema_status = "stale"

    overall = "ok" if db_status == "ok" and schema_status == "ok" else "degraded"
    return {
        "status": overall,
        "db": db_status,
        "schema": schema_status,
        "db_revision": db_revision,
        "code_revision": _CODE_REVISION,
    }
