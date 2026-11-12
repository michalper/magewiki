from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Same pgvector cosine-distance operator and CTE shape as hybrid.py's own
# semantic signal -- comparing two already-stored vectors directly, so
# (unlike hybrid_search) no query embedding needs to be computed/formatted
# as a string literal here.
_SIMILAR_SQL = text("""
WITH target AS (
    SELECT c.module_id, c.embedding, COALESCE(m.composer_name, m.name) AS identity
    FROM chunks c
    JOIN modules m ON m.id = c.module_id
    WHERE c.module_id = :module_id AND c.chunk_type = 'module'
)
SELECT c.module_id, m.name, m.composer_name,
       1 - (c.embedding <=> target.embedding) AS similarity,
       target.identity AS target_identity
FROM chunks c
JOIN target ON true
JOIN modules m ON m.id = c.module_id
WHERE c.chunk_type = 'module' AND c.module_id != target.module_id
ORDER BY c.embedding <=> target.embedding
LIMIT :limit
""")


@dataclass
class SimilarModule:
    module_id: int
    name: str
    composer_name: str | None
    similarity: float


async def find_similar_modules(
    session: AsyncSession, module_id: int, limit: int = 10, min_similarity: float = 0.5
) -> list[SimilarModule]:
    """The most semantically similar other modules to `module_id`, by cosine
    similarity over Phase 4's existing module-level embeddings (chunks.chunk_type
    == 'module', exactly one row per analyzed module, see app/tasks/jobs.py's
    embed_chunks) -- no new scan, no new embedding API call. `min_similarity`
    is a judgment-call default (same spirit as LICENSE_RISK_PREFIXES: this
    project's own opinion on "similar enough to be worth surfacing," not a
    universal threshold), not something fetched from settings.

    Fleet-wide, not scoped to one repo_root -- unlike cross-module conflict
    detection (which must stay per-store, matching Magento's own per-store
    declarative-merge semantics), "do we have two modules doing the same
    third-party integration" is a genuinely cross-repo question.

    Returns [] if `module_id` has no 'module' chunk yet (not analyzed/
    embedded) -- the `target` CTE comes back empty, so the `JOIN target ON
    true` yields zero rows; same "doesn't exist yet" handling
    hybrid.py/evaluation/faithfulness.py already use for this table.
    """
    # Over-fetch (limit * 4) before filtering, since the same-vendor exclusion
    # and the min_similarity cutoff below can both drop real SQL-returned rows
    # -- filtering first, then capping to `limit`, keeps the final list
    # genuinely the top-`limit` *eligible* matches, not a short list merely
    # because the first few SQL rows happened to get filtered out.
    rows = (
        await session.execute(_SIMILAR_SQL, {"module_id": module_id, "limit": limit * 4})
    ).all()

    results: list[SimilarModule] = []
    for row in rows:
        if row.similarity < min_similarity:
            continue
        identity = row.composer_name or row.name
        if identity == row.target_identity:
            continue
        results.append(
            SimilarModule(
                module_id=row.module_id, name=row.name, composer_name=row.composer_name, similarity=row.similarity
            )
        )
        if len(results) >= limit:
            break
    return results
