from decimal import Decimal

from app.analyzer.pricing import compute_cost_usd


def test_compute_cost_usd_for_a_known_model():
    cost = compute_cost_usd("anthropic/claude-haiku-5-5", tokens_in=1_000_000, tokens_out=1_000_000)
    assert cost == Decimal("6.00")


def test_compute_cost_usd_is_zero_for_an_unknown_model():
    assert compute_cost_usd("some/unpriced-model", tokens_in=1000, tokens_out=1000) == Decimal(0)
