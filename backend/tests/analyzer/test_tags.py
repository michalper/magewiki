from app.analyzer.schemas import Tag
from app.analyzer.tags import ALLOWED_TAGS, derive_parser_tags, filter_tags, merge_tags


def test_derive_parser_tags_matches_known_dependencies():
    tags = derive_parser_tags(["Magento_Sales", "Magento_Payment", "Magento_Unrelated"])
    names = {t.name for t in tags}
    assert names == {"checkout", "payments"}
    assert all(t.source == "parser" and t.confidence == 1.0 for t in tags)


def test_derive_parser_tags_empty_when_no_match():
    assert derive_parser_tags(["Magento_Backend_Nonexistent"]) == []


def test_filter_tags_keeps_allowed_ai_tags():
    tags = [Tag(name="payments", source="ai", confidence=0.9)]
    kept, rejected = filter_tags(tags)
    assert kept == tags
    assert rejected == []


def test_filter_tags_drops_out_of_vocabulary_ai_tags():
    tags = [Tag(name="totally-made-up", source="ai", confidence=0.9)]
    kept, rejected = filter_tags(tags)
    assert kept == []
    assert rejected == ["totally-made-up"]


def test_filter_tags_does_not_trust_a_self_claimed_parser_source():
    # filter_tags only ever receives doc.tags (raw, untrusted LLM output) —
    # genuine parser tags come from derive_parser_tags() and are merged in
    # separately, so an out-of-vocabulary tag claiming source="parser" here
    # must still be rejected, or the model could bypass ALLOWED_TAGS just by
    # setting that field itself.
    tags = [Tag(name="not-in-vocab-but-claims-parser-sourced", source="parser", confidence=1.0)]
    kept, rejected = filter_tags(tags)
    assert kept == []
    assert rejected == ["not-in-vocab-but-claims-parser-sourced"]


def test_merge_tags_dedupes_by_name_preferring_parser_source():
    parser_tags = [Tag(name="checkout", source="parser", confidence=1.0)]
    ai_tags = [Tag(name="checkout", source="ai", confidence=0.7), Tag(name="marketing", source="ai", confidence=0.6)]

    merged = merge_tags(parser_tags, ai_tags)

    assert len(merged) == 2
    by_name = {t.name: t for t in merged}
    assert by_name["checkout"].source == "parser"
    assert by_name["marketing"].source == "ai"


def test_allowed_tags_matches_claude_md_vocabulary():
    assert ALLOWED_TAGS == frozenset(
        {
            "payments", "shipping", "marketing", "erp", "search",
            "seo", "checkout", "admin-tools", "performance", "b2b",
            "inventory", "catalog", "customer", "cms", "graphql",
            "api", "analytics", "security", "multi-store", "theme",
            "pwa", "cron",
        }
    )


def test_derive_parser_tags_matches_newly_expanded_vocabulary_dependencies():
    tags = derive_parser_tags(["Magento_Inventory", "Magento_Customer", "Magento_GraphQl", "Magento_Cron"])
    names = {t.name for t in tags}
    assert names == {"inventory", "customer", "graphql", "cron"}
