import pytest

from app.evaluation.metrics import aggregate, hit_at_k, reciprocal_rank


def test_hit_at_k_true_when_relevant_within_k():
    assert hit_at_k([5, 2, 9], {2}, k=3) is True


def test_hit_at_k_false_when_relevant_only_past_k():
    assert hit_at_k([5, 2, 9], {9}, k=2) is False


def test_hit_at_k_false_when_relevant_absent():
    assert hit_at_k([5, 2, 9], {1}, k=3) is False


def test_hit_at_k_raises_on_empty_relevant_ids():
    with pytest.raises(ValueError):
        hit_at_k([5, 2, 9], set(), k=3)


def test_reciprocal_rank_first_hit():
    assert reciprocal_rank([5, 2, 9], {5}) == 1.0


def test_reciprocal_rank_third_hit():
    assert reciprocal_rank([5, 2, 9], {9}) == pytest.approx(1 / 3)


def test_reciprocal_rank_miss():
    assert reciprocal_rank([5, 2, 9], {1}) == 0.0


def test_reciprocal_rank_raises_on_empty_relevant_ids():
    with pytest.raises(ValueError):
        reciprocal_rank([5, 2, 9], set())


def test_aggregate_exact_values_over_three_questions():
    # q1: hit at rank 1 -> recall@1/3 true, rr=1.0
    # q2: hit at rank 3 -> recall@1 false, recall@3 true, rr=1/3
    # q3: miss entirely -> recall@1/3 false, rr=0.0
    per_question = [
        ([1, 2, 3], {1}),
        ([2, 5, 3], {3}),
        ([2, 5, 9], {1}),
    ]

    result = aggregate(per_question, ks=(1, 3))

    assert result["recall@1"] == pytest.approx(1 / 3)
    assert result["recall@3"] == pytest.approx(2 / 3)
    assert result["mrr"] == pytest.approx((1.0 + 1 / 3 + 0.0) / 3)


def test_aggregate_raises_on_empty_input():
    with pytest.raises(ValueError):
        aggregate([])
