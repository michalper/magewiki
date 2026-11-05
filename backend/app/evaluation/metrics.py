from collections.abc import Sequence

DEFAULT_KS: tuple[int, ...] = (1, 3, 5, 10)


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
