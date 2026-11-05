from app.analyzer.schemas import Tag

ALLOWED_TAGS = frozenset(
    {
        "payments",
        "shipping",
        "marketing",
        "erp",
        "search",
        "seo",
        "checkout",
        "admin-tools",
        "performance",
        "b2b",
    }
)

# Deterministic dependency-name -> tag signals (CLAUDE.md: "deterministic signals reinforce AI-assigned tags").
_DEPENDENCY_TAG_SIGNALS: dict[str, str] = {
    "Magento_Payment": "payments",
    "Magento_Paypal": "payments",
    "Magento_Vault": "payments",
    "Magento_Shipping": "shipping",
    "Magento_Sales": "checkout",
    "Magento_Checkout": "checkout",
    "Magento_Quote": "checkout",
    "Magento_SalesRule": "marketing",
    "Magento_Newsletter": "marketing",
    "Magento_CatalogSearch": "search",
    "Magento_Elasticsearch": "search",
    "Magento_Search": "search",
    "Magento_Cms": "seo",
    "Magento_UrlRewrite": "seo",
    "Magento_AdminGws": "admin-tools",
    "Magento_Backend": "admin-tools",
    "Magento_PageCache": "performance",
    "Magento_Amqp": "performance",
    "Magento_NegotiableQuote": "b2b",
    "Magento_Company": "b2b",
}


def derive_parser_tags(dependency_names: list[str]) -> list[Tag]:
    found = {
        _DEPENDENCY_TAG_SIGNALS[name] for name in dependency_names if name in _DEPENDENCY_TAG_SIGNALS
    }
    return [Tag(name=tag, source="parser", confidence=1.0) for tag in sorted(found)]


def filter_tags(tags: list[Tag]) -> tuple[list[Tag], list[str]]:
    kept: list[Tag] = []
    rejected: list[str] = []
    for tag in tags:
        if tag.source == "parser" or tag.name in ALLOWED_TAGS:
            kept.append(tag)
        else:
            rejected.append(tag.name)
    return kept, rejected


def merge_tags(parser_tags: list[Tag], ai_tags: list[Tag]) -> list[Tag]:
    """Combine parser- and AI-sourced tags, deduping by name — the deterministic
    parser signal wins when both independently land on the same tag.
    """
    merged: dict[str, Tag] = {tag.name: tag for tag in parser_tags}
    for tag in ai_tags:
        merged.setdefault(tag.name, tag)
    return list(merged.values())
