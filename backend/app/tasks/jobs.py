from sqlalchemy import update

from app.db import async_session_factory
from app.models import FileHash, Module


async def analyze_file(
    ctx: dict,
    module_id: int,
    relative_path: str,
    content_hash: str,
    module_current_hash: str,
) -> None:
    """Phase 2 stub: no AI work yet (Phase 3 replaces this body with the real
    analysis). Marks the file as analyzed and, if it was the last outstanding
    file for this scan generation, flips the module to up_to_date.
    """
    try:
        async with async_session_factory() as session, session.begin():
            marked = await session.execute(
                update(FileHash)
                .where(
                    FileHash.module_id == module_id,
                    FileHash.relative_path == relative_path,
                    FileHash.content_hash == content_hash,
                    FileHash.analyzed.is_(False),
                )
                .values(analyzed=True)
                .returning(FileHash.id)
            )
            if marked.first() is None:
                # Stale retry (already handled) or a newer scan superseded this
                # file — nothing to do.
                return

            decremented = await session.execute(
                update(Module)
                .where(Module.id == module_id, Module.current_hash == module_current_hash)
                .values(pending_file_count=Module.pending_file_count - 1, state="analyzing")
                .returning(Module.pending_file_count)
            )
            row = decremented.first()
            if row is not None and row.pending_file_count == 0:
                await session.execute(
                    update(Module)
                    .where(
                        Module.id == module_id,
                        Module.current_hash == module_current_hash,
                        Module.pending_file_count == 0,
                    )
                    .values(state="up_to_date", analyzed_hash=module_current_hash, last_error=None, retry_count=0)
                )
    except Exception as exc:
        async with async_session_factory() as session, session.begin():
            await session.execute(
                update(Module)
                .where(Module.id == module_id)
                .values(state="failed", retry_count=Module.retry_count + 1, last_error=str(exc))
            )
        raise
