"""Eval-only signal isolation for comparing vector-only and keyword-only retrieval
against the production hybrid (RRF-fused) retriever. These queries are kept in
sync BY HAND with the `semantic`/`keyword` CTEs in app.search.hybrid._SEARCH_SQL —
app.search.hybrid is settled production architecture and is not refactored to
serve this one-time evaluation need.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyzer.embeddings import embed_query_text
from app.runtime_config import resolve_embedding_config
from app.search.hybrid import SearchResult

# Mirrors the `semantic` CTE in app/search/hybrid.py::_SEARCH_SQL.
_VECTOR_ONLY_SQL = text("""
    SELECT c.id, c.chunk_type, c.module_id, m.name AS module_name, c.relative_path, c.text,
           1.0 - (c.embedding <=> (:query_embedding)::vector) AS score
    FROM chunks c
    JOIN modules m ON m.id = c.module_id
    ORDER BY c.embedding <=> (:query_embedding)::vector
    LIMIT :limit
""")

# Mirrors the `keyword` CTE in app/search/hybrid.py::_SEARCH_SQL.
_KEYWORD_ONLY_SQL = text("""
    SELECT c.id, c.chunk_type, c.module_id, m.name AS module_name, c.relative_path, c.text,
           ts_rank_cd(c.tsv, websearch_to_tsquery('english', :query_text)) AS score
    FROM chunks c
    JOIN modules m ON m.id = c.module_id
    WHERE c.tsv @@ websearch_to_tsquery('english', :query_text)
    ORDER BY score DESC
    LIMIT :limit
""")


def _rows_to_results(rows) -> list[SearchResult]:
    return [
        SearchResult(
            chunk_id=row.id,
            chunk_type=row.chunk_type,
            module_id=row.module_id,
            module_name=row.module_name,
            relative_path=row.relative_path,
            text=row.text,
            score=float(row.score),
        )
        for row in rows
    ]


async def vector_only_search(session: AsyncSession, query_text_: str, limit: int = 10) -> list[SearchResult]:
    embed_config = await resolve_embedding_config(session)
    query_embedding = await embed_query_text(
        query_text_, model=embed_config.model, api_key=embed_config.api_key, api_base=embed_config.api_base
    )
    vector_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"

    rows = await session.execute(_VECTOR_ONLY_SQL, {"query_embedding": vector_literal, "limit": limit})
    return _rows_to_results(rows)


async def keyword_only_search(session: AsyncSession, query_text_: str, limit: int = 10) -> list[SearchResult]:
    rows = await session.execute(_KEYWORD_ONLY_SQL, {"query_text": query_text_, "limit": limit})
    return _rows_to_results(rows)
