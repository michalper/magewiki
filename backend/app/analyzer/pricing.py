from decimal import Decimal

# Fallback price table, used only when litellm.completion_cost() doesn't return a
# usable positive number for the configured model. Prices are USD per million
# tokens; check against Anthropic's current pricing page before trusting this for
# a new model — litellm's own cost table is the primary source of truth.
MODEL_PRICES_USD_PER_MTOK: dict[str, dict[str, Decimal]] = {
    "anthropic/claude-haiku-5-5": {"input": Decimal("1.00"), "output": Decimal("5.00")},
}


def compute_cost_usd(model: str, tokens_in: int, tokens_out: int) -> Decimal:
    prices = MODEL_PRICES_USD_PER_MTOK.get(model)
    if prices is None:
        return Decimal("0")
    return (Decimal(tokens_in) * prices["input"] + Decimal(tokens_out) * prices["output"]) / Decimal(1_000_000)
