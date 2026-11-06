"""Small, committed, zero-cost dataset for the CI "RAG eval" PR comment
(Phase 7b). Deliberately NOT the real Ordo_Automation numbers from Phase 7's
README table — those need a fixture that only exists on the author's machine
plus paid API keys, neither available to a CI runner. These scenarios use the
same hand-built-embedding technique as
backend/tests/evaluation/test_fast_retrieval_regression.py: each is
constructed so neither the vector-only nor the keyword-only signal alone
ranks the relevant chunk at #1, but RRF fusion does — a free, deterministic
regression signal that the hybrid retriever's fusion keeps working, not a
measure of real-world retrieval quality.

Each scenario uses its own base dimension `d` (spaced 10 apart so scenarios
never interfere with each other's vector ranking):
- target: {d: 0.9, d+1: 0.1} — a *unique*, non-zero similarity to the query
  (strictly between vector_noise's 1.0 and the "irrelevant" group's 0.0), so
  its semantic rank is always exactly 2, never an accident of tie-breaking.
- vector_noise: {d: 1.0} — exact match to the query vector, always rank 1.
- keyword_noise: {d: -0.5, d+2: 1.0} — a *negative* projection onto the
  query's own axis, strictly worse than every unrelated ("tied at zero")
  chunk, so it always ranks last on the semantic signal regardless of how
  many other chunks (other scenarios', or leftover dev-DB rows) happen to be
  tied at zero similarity. Without this negative tilt, keyword_noise would
  share the zero-similarity tie with everything else and could occasionally
  out-rank target by sheer luck of Postgres's tie-break order — this is the
  bug that made an earlier version of this dataset flaky when run with
  several scenarios seeded into the same table at once.
"""

from dataclasses import dataclass

from app.config import settings

DIM_SPACING = 10


def _vector(active: dict[int, float]) -> list[float]:
    v = [0.0] * settings.embedding_dimensions
    for i, val in active.items():
        v[i] = val
    return v


@dataclass(frozen=True)
class CiChunk:
    relative_path: str
    text: str
    embedding: list[float]


@dataclass(frozen=True)
class CiScenario:
    id: str
    query: str
    relevant_relative_path: str
    chunks: list[CiChunk]


def _make_scenario(id: str, keyword: str, base_dim: int) -> CiScenario:
    d = base_dim
    return CiScenario(
        id=id,
        query=keyword,
        relevant_relative_path="target.php",
        chunks=[
            CiChunk(
                relative_path="target.php",
                text=f"This file is the actually relevant one and mentions {keyword} once.",
                embedding=_vector({d: 0.9, d + 1: 0.1}),
            ),
            CiChunk(
                relative_path="vector_noise.php",
                text="This file is unrelated noise with no special terms at all.",
                embedding=_vector({d: 1.0}),
            ),
            CiChunk(
                relative_path="keyword_noise.php",
                text=f"{keyword} {keyword} {keyword} dominates this unrelated file about {keyword}.",
                embedding=_vector({d: -0.5, d + 2: 1.0}),
            ),
        ],
    )


CI_SCENARIOS: list[CiScenario] = [
    _make_scenario("ci-1", "zyzzyvaspecialalpha", base_dim=0 * DIM_SPACING),
    _make_scenario("ci-2", "quetzalcoatlusbeta", base_dim=1 * DIM_SPACING),
    _make_scenario("ci-3", "xylophonegamma", base_dim=2 * DIM_SPACING),
    _make_scenario("ci-4", "wigglesworthdelta", base_dim=3 * DIM_SPACING),
]
