import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.loop import run_agent
from app.agent.prompt import AUDIENCE_DEV, AUDIENCE_PM
from app.db import get_session

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    audience: str = AUDIENCE_DEV


def _format_sse(event: dict) -> str:
    event_type = event["event"]
    payload = {k: v for k, v in event.items() if k != "event"}
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


async def _sse_stream(session: AsyncSession, messages: list[dict], audience: str) -> AsyncIterator[str]:
    async for event in run_agent(session, messages, audience):
        yield _format_sse(event)


@router.post("/chat")
async def chat(request: ChatRequest, session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    audience = request.audience if request.audience in (AUDIENCE_PM, AUDIENCE_DEV) else AUDIENCE_DEV
    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    return StreamingResponse(_sse_stream(session, messages, audience), media_type="text/event-stream")
