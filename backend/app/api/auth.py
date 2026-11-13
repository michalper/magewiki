import hmac

from fastapi import HTTPException, Request

from app.config import settings


async def require_write_access(request: Request) -> None:
    """Gate for endpoints that cost money or mutate shared global state
    (POST /chat, PATCH /settings/llm, POST /scan[/stream]). A no-op when
    settings.write_access_token is unset, preserving today's open behavior
    for local/self-hosted use — see CLAUDE.md's Phase 24 decision note.
    """
    if not settings.write_access_token:
        return
    provided = request.headers.get("X-Access-Token", "")
    if not hmac.compare_digest(provided, settings.write_access_token):
        raise HTTPException(status_code=401, detail="missing or invalid access token")
