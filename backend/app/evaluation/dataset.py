"""Hand-curated eval question set, verified against the real Ordo_Automation
fixture (MAGEWIKI_ORDO_FIXTURE_PATH) by direct inspection of its source during
Phase 7 planning — see backend/tests/test_real_ordo_fixture.py for the same
fixture's already-asserted facts (3 plugins, 11 observers, 5 dependencies).

`category` on a RetrievalQuestion is the author's hypothesis about which signal
should surface it, not a guarantee — the eval runner reports what every mode
actually scores, even when it contradicts the label.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

MODULE_SENTINEL = "<module>"
MODULE_ID_PLACEHOLDER = "__MODULE_ID__"


@dataclass(frozen=True)
class RetrievalQuestion:
    id: str
    query: str
    category: str  # "semantic" | "keyword" | "identifier" | "hybrid"
    relevant_relative_paths: frozenset[str]


@dataclass(frozen=True)
class EnumerationQuestion:
    id: str
    query: str
    tool: str
    tool_kwargs: dict = field(default_factory=dict)
    expected: Callable[[dict], bool] = lambda result: True


@dataclass(frozen=True)
class NegativeQuestion:
    id: str
    query: str
    mode: str  # "tool" | "agent"
    tool: str | None = None
    tool_kwargs: dict | None = None
    expected_empty: Callable[[dict], bool] | None = None
    expected_answer: Callable[[str], bool] | None = None


RETRIEVAL_QUESTIONS: list[RetrievalQuestion] = [
    RetrievalQuestion(
        id="sem-1",
        query=(
            "How does this module avoid emailing the same win-back message twice to "
            "someone whose inactive/active status keeps flipping?"
        ),
        category="semantic",
        relevant_relative_paths=frozenset({"Cron/SendWinBackEmails.php"}),
    ),
    RetrievalQuestion(
        id="sem-2",
        query=(
            "How does the module sync customer emails to Google for ad remarketing "
            "without exposing plaintext email addresses?"
        ),
        category="semantic",
        relevant_relative_paths=frozenset({"Model/AdAudience/GoogleAdsSyncClient.php"}),
    ),
    RetrievalQuestion(
        id="sem-3",
        query=(
            "What stops a B2B customer from placing an order once they've spent "
            "beyond their approved credit?"
        ),
        category="semantic",
        relevant_relative_paths=frozenset(
            {"Plugin/Quote/BlockOverLimitCheckout.php", "Model/CreditLimitCalculator.php"}
        ),
    ),
    RetrievalQuestion(
        id="sem-4",
        query=(
            "How are customers ranked by recency, frequency, and monetary value for "
            "marketing segmentation?"
        ),
        category="semantic",
        relevant_relative_paths=frozenset(
            {"Cron/RecomputeRfmScores.php", "Model/Rfm/RfmCalculator.php"}
        ),
    ),
    RetrievalQuestion(
        id="kw-1",
        query="OfflineUserDataJobService",
        category="keyword",
        relevant_relative_paths=frozenset({"Model/AdAudience/GoogleAdsSyncClient.php"}),
    ),
    RetrievalQuestion(
        id="kw-2",
        query="win_back_sent tag",
        category="keyword",
        relevant_relative_paths=frozenset({"Cron/SendWinBackEmails.php"}),
    ),
    RetrievalQuestion(
        id="id-1",
        query="GoogleAdsSyncClint",  # deliberate typo
        category="identifier",
        relevant_relative_paths=frozenset({"Model/AdAudience/GoogleAdsSyncClient.php"}),
    ),
    RetrievalQuestion(
        id="id-2",
        query="BlockOverLimitChecout",  # deliberate typo
        category="identifier",
        relevant_relative_paths=frozenset({"Plugin/Quote/BlockOverLimitCheckout.php"}),
    ),
    RetrievalQuestion(
        id="hyb-1",
        query="credit limit checkout block plugin beforePlaceOrder",
        category="hybrid",
        relevant_relative_paths=frozenset({"Plugin/Quote/BlockOverLimitCheckout.php"}),
    ),
    RetrievalQuestion(
        id="hyb-2",
        query="win back inactive customer email tag",
        category="hybrid",
        relevant_relative_paths=frozenset({"Cron/SendWinBackEmails.php"}),
    ),
]

ENUMERATION_QUESTIONS: list[EnumerationQuestion] = [
    EnumerationQuestion(
        id="enum-1",
        query="How many classes in Ordo_Automation are Magento plugins?",
        tool="find_by_class",
        tool_kwargs={"identifier": "Ordo\\Automation"},
        expected=lambda result: sum(c["is_plugin"] for c in result["defined_in"]) == 3,
    ),
    EnumerationQuestion(
        id="enum-2",
        query="How many classes in Ordo_Automation are event observers?",
        tool="find_by_class",
        tool_kwargs={"identifier": "Ordo\\Automation"},
        expected=lambda result: sum(c["is_observer"] for c in result["defined_in"]) == 11,
    ),
    EnumerationQuestion(
        id="enum-3",
        query="How many observers listen to the sales_order_place_after event?",
        tool="find_by_event",
        tool_kwargs={"event_name": "sales_order_place_after"},
        expected=lambda result: len(result["results"]) == 3,
    ),
    EnumerationQuestion(
        id="enum-4",
        query="How many Magento modules does Ordo_Automation declare a dependency on?",
        tool="get_dependencies",
        tool_kwargs={"module_id": MODULE_ID_PLACEHOLDER},
        expected=lambda result: len(result["depends_on"]) == 5,
    ),
    EnumerationQuestion(
        id="enum-5",
        query="How many modules are currently catalogued?",
        tool="list_modules",
        tool_kwargs={},
        expected=lambda result: result["total"] == 1,
    ),
]

NEGATIVE_QUESTIONS: list[NegativeQuestion] = [
    NegativeQuestion(
        id="neg-1",
        query="Which plugin in this module targets Magento\\Catalog\\Model\\Product::save?",
        mode="tool",
        tool="find_by_class",
        tool_kwargs={"identifier": "Magento\\Catalog\\Model\\Product"},
        expected_empty=lambda result: result["plugins_targeting_it"] == [],
    ),
    NegativeQuestion(
        id="neg-2",
        query="Read the file Helper/ShippingRateCalculator.php",
        mode="tool",
        tool="read_file",
        tool_kwargs={"module_id": MODULE_ID_PLACEHOLDER, "relative_path": "Helper/ShippingRateCalculator.php"},
        expected_empty=lambda result: result["found"] is False,
    ),
    NegativeQuestion(
        id="neg-3",
        query="Does Ordo_Automation have a Klaviyo email integration?",
        mode="agent",
        expected_answer=lambda text: "klaviyo" not in text.lower()
        or any(
            phrase in text.lower()
            for phrase in (
                "not found",
                "no evidence",
                "could not find",
                "doesn't appear",
                "does not integrate",
                "no integration",
                "couldn't find",
            )
        ),
    ),
]
