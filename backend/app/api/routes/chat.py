import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.loop import run_agent
from app.agent.prompt import AUDIENCE_DEV, AUDIENCE_PM
from app.api.auth import require_write_access
from app.api.sse import format_sse
from app.db import get_session

router = APIRouter()
logger = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    audience: str = AUDIENCE_DEV


async def _sse_stream(session: AsyncSession, messages: list[dict], audience: str) -> AsyncIterator[str]:
    try:
        async for event in run_agent(session, messages, audience):
            yield format_sse(event)
    except Exception:
        # Without this, an exception from run_agent (a DB hiccup, an LLM call
        # erroring deep in the tool loop) just drops the connection — the async
        # generator stops, the chat UI never sees an "error"/"done" event, and
        # the message is left looking like it's still streaming indefinitely.
        logger.exception("unexpected error during chat streaming")
        yield format_sse({"event": "error", "detail": "chat failed unexpectedly — check server logs"})


@router.post("/chat", dependencies=[Depends(require_write_access)])
async def chat(request: ChatRequest, session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    audience = request.audience if request.audience in (AUDIENCE_PM, AUDIENCE_DEV) else AUDIENCE_DEV
    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    return StreamingResponse(_sse_stream(session, messages, audience), media_type="text/event-stream")
