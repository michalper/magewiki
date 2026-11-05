from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analyzer.embeddings import embed_query_text
from app.runtime_config import resolve_embedding_config

# Reciprocal Rank Fusion (k=60) over three signals — semantic (pgvector cosine
# distance), keyword (tsvector full-text), and identifier (pg_trgm fuzzy match on
# module/class names). Each CTE explicitly ORDERs BY its own ranking criterion
# before LIMIT, so the rows kept by LIMIT are actually the top-k by that signal —
# relying on the window function's ORDER BY alone would not guarantee that.
_SEARCH_SQL = text("""
WITH semantic AS (
    SELECT id AS chunk_id,
           row_number() OVER (ORDER BY embedding <=> (:query_embedding)::vector) AS rnk
    FROM chunks
    ORDER BY embedding <=> (:query_embedding)::vector
    LIMIT :topk
),
keyword AS (
    SELECT id AS chunk_id,
           row_number() OVER (ORDER BY ts_rank_cd(tsv, websearch_to_tsquery('english', :query_text)) DESC) AS rnk
    FROM chunks
    WHERE tsv @@ websearch_to_tsquery('english', :query_text)
    ORDER BY ts_rank_cd(tsv, websearch_to_tsquery('english', :query_text)) DESC
    LIMIT :topk
),
identifier_hits AS (
    SELECT m.id AS module_id, NULL::text AS relative_path, similarity(m.name, :query_text) AS sim
    FROM modules m
    WHERE similarity(m.name, :query_text) > :trgm_threshold
    UNION ALL
    SELECT pc.module_id, pc.file_path,
           GREATEST(similarity(pc.fqcn, :query_text), similarity(pc.class_name, :query_text)) AS sim
    FROM php_classes pc
    WHERE similarity(pc.fqcn, :query_text) > :trgm_threshold
       OR similarity(pc.class_name, :query_text) > :trgm_threshold
),
identifiers AS (
    SELECT ch.id AS chunk_id,
           row_number() OVER (ORDER BY ih.sim DESC) AS rnk
    FROM identifier_hits ih
    JOIN chunks ch ON ch.module_id = ih.module_id
        AND (ih.relative_path IS NULL OR ch.relative_path = ih.relative_path OR ch.chunk_type = 'module')
    ORDER BY ih.sim DESC
    LIMIT :topk
),
fused AS (
    SELECT chunk_id, SUM(1.0 / (60 + rnk)) AS rrf_score
    FROM (
        SELECT chunk_id, rnk FROM semantic
        UNION ALL SELECT chunk_id, rnk FROM keyword
        UNION ALL SELECT chunk_id, rnk FROM identifiers
    ) combined
    GROUP BY chunk_id
)
SELECT c.id, c.chunk_type, c.module_id, m.name AS module_name, c.relative_path, c.text, f.rrf_score
FROM fused f
JOIN chunks c ON c.id = f.chunk_id
JOIN modules m ON m.id = c.module_id
ORDER BY f.rrf_score DESC
LIMIT :limit
""")


@dataclass
class SearchResult:
    chunk_id: int
    chunk_type: str
    module_id: int
    module_name: str
    relative_path: str | None
    text: str
    score: float


async def hybrid_search(
    session: AsyncSession,
    query_text: str,
    limit: int = 10,
    topk: int = 50,
    trgm_threshold: float = 0.3,
) -> list[SearchResult]:
    embed_config = await resolve_embedding_config(session)
    query_embedding = await embed_query_text(query_text, model=embed_config.model, api_key=embed_config.api_key)
    vector_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"

    rows = await session.execute(
        _SEARCH_SQL,
        {
            "query_embedding": vector_literal,
            "query_text": query_text,
            "topk": topk,
            "trgm_threshold": trgm_threshold,
            "limit": limit,
        },
    )
    return [
        SearchResult(
            chunk_id=row.id,
            chunk_type=row.chunk_type,
            module_id=row.module_id,
            module_name=row.module_name,
            relative_path=row.relative_path,
            text=row.text,
            score=float(row.rrf_score),
        )
        for row in rows
    ]
