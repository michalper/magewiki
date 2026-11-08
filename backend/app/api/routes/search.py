from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.search.hybrid import hybrid_search

router = APIRouter()


class SearchResultResponse(BaseModel):
    chunk_id: int
    chunk_type: str
    module_id: int
    module_name: str
    relative_path: str | None
    text: str
    score: float
    semantic_rank: int | None
    keyword_rank: int | None
    identifier_rank: int | None


@router.get("/search", response_model=list[SearchResultResponse])
async def search(
    q: str, limit: int = 10, session: AsyncSession = Depends(get_session)
) -> list[SearchResultResponse]:
    results = await hybrid_search(session, q, limit=limit)
    return [
        SearchResultResponse(
            chunk_id=r.chunk_id,
            chunk_type=r.chunk_type,
            module_id=r.module_id,
            module_name=r.module_name,
            relative_path=r.relative_path,
            text=r.text,
            score=r.score,
            semantic_rank=r.semantic_rank,
            keyword_rank=r.keyword_rank,
            identifier_rank=r.identifier_rank,
        )
        for r in results
    ]
