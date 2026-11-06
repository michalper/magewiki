from collections.abc import Sequence

DEFAULT_KS: tuple[int, ...] = (1, 3, 5, 10)
MODE_LABELS: dict[str, str] = {"vector": "Vector-only", "keyword": "FTS-only", "hybrid": "Hybrid (RRF)"}


def hit_at_k(ranked_ids: Sequence[int], relevant_ids: set[int], k: int) -> bool:
    """True if any relevant id appears in the top k ranked ids."""
    if not relevant_ids:
        raise ValueError("relevant_ids must be non-empty")
    return any(rid in relevant_ids for rid in ranked_ids[:k])


def reciprocal_rank(ranked_ids: Sequence[int], relevant_ids: set[int]) -> float:
    """1/rank of the first relevant id in ranked_ids, or 0.0 if none appears."""
    if not relevant_ids:
        raise ValueError("relevant_ids must be non-empty")
    for i, rid in enumerate(ranked_ids, start=1):
        if rid in relevant_ids:
            return 1.0 / i
    return 0.0


def aggregate(
    per_question: list[tuple[Sequence[int], set[int]]], ks: tuple[int, ...] = DEFAULT_KS
) -> dict[str, float]:
    """Mean recall@k (for each k) and MRR over a list of (ranked_ids, relevant_ids) pairs."""
    if not per_question:
        raise ValueError("per_question must be non-empty")
    n = len(per_question)
    result = {
        f"recall@{k}": sum(hit_at_k(ranked, relevant, k) for ranked, relevant in per_question) / n
        for k in ks
    }
    result["mrr"] = sum(reciprocal_rank(ranked, relevant) for ranked, relevant in per_question) / n
    return result


def render_markdown_table(metrics: dict[str, dict[str, float]], ks: tuple[int, ...] = DEFAULT_KS) -> str:
    """A `| Mode | recall@k... | MRR |` table for vector/keyword/hybrid metrics."""
    header = "| Mode | " + " | ".join(f"recall@{k}" for k in ks) + " | MRR |"
    sep = "|---" * (len(ks) + 2) + "|"
    rows = []
    for mode in ("vector", "keyword", "hybrid"):
        m = metrics[mode]
        cells = " | ".join(f"{m[f'recall@{k}']:.2f}" for k in ks)
        rows.append(f"| {MODE_LABELS[mode]} | {cells} | {m['mrr']:.2f} |")
    return "\n".join([header, sep, *rows])
