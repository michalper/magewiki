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


_DUPLICATE_PAIRS_SQL = text("""
SELECT c1.module_id AS a_id, m1.name AS a_name, m1.composer_name AS a_composer,
       c2.module_id AS b_id, m2.name AS b_name, m2.composer_name AS b_composer,
       1 - (c1.embedding <=> c2.embedding) AS similarity
FROM chunks c1
JOIN chunks c2 ON c2.chunk_type = 'module' AND c2.module_id > c1.module_id
JOIN modules m1 ON m1.id = c1.module_id
JOIN modules m2 ON m2.id = c2.module_id
WHERE c1.chunk_type = 'module'
ORDER BY similarity DESC
LIMIT :limit
""")


@dataclass
class SimilarModule:
    module_id: int
    name: str
    composer_name: str | None
    similarity: float


@dataclass
class DuplicateModulePair:
    module_a_id: int
    module_a_name: str
    module_a_composer_name: str | None
    module_b_id: int
    module_b_name: str
    module_b_composer_name: str | None
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


async def find_duplicate_module_pairs(
    session: AsyncSession, min_similarity: float = 0.5, limit: int = 50
) -> list[DuplicateModulePair]:
    """Every pair of modules fleet-wide whose module-level embeddings are
    close but aren't the same vendor/package -- the same relationship
    find_similar_modules surfaces one module at a time, computed for the
    whole fleet at once (e.g. for a "possible duplicates" overview). `c2.
    module_id > c1.module_id` in the self-join rules out both self-pairs
    and mirrored duplicates (A,B and B,A).
    """
    rows = (await session.execute(_DUPLICATE_PAIRS_SQL, {"limit": limit * 4})).all()

    results: list[DuplicateModulePair] = []
    for row in rows:
        if row.similarity < min_similarity:
            continue
        a_identity = row.a_composer or row.a_name
        b_identity = row.b_composer or row.b_name
        if a_identity == b_identity:
            continue
        results.append(
            DuplicateModulePair(
                module_a_id=row.a_id,
                module_a_name=row.a_name,
                module_a_composer_name=row.a_composer,
                module_b_id=row.b_id,
                module_b_name=row.b_name,
                module_b_composer_name=row.b_composer,
                similarity=row.similarity,
            )
        )
        if len(results) >= limit:
            break
    return results
