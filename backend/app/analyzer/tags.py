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
        # Expanded 2026-11-07 from CLAUDE.md's "starter tag vocabulary" — the
        # original 10 under-categorized a real 760-module fleet (lots of
        # inventory/catalog/customer/cms/graphql/api modules had no tag that
        # actually fit).
        "inventory",
        "catalog",
        "customer",
        "cms",
        "graphql",
        "api",
        "analytics",
        "security",
        "multi-store",
        "theme",
        "pwa",
        "cron",
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
    "Magento_UrlRewrite": "seo",
    "Magento_AdminGws": "admin-tools",
    "Magento_Backend": "admin-tools",
    "Magento_PageCache": "performance",
    "Magento_Amqp": "performance",
    "Magento_NegotiableQuote": "b2b",
    "Magento_Company": "b2b",
    "Magento_Inventory": "inventory",
    "Magento_InventoryApi": "inventory",
    "Magento_InventorySales": "inventory",
    "Magento_Catalog": "catalog",
    "Magento_CatalogInventory": "catalog",
    "Magento_Customer": "customer",
    "Magento_Cms": "cms",
    "Magento_PageBuilder": "cms",
    "Magento_GraphQl": "graphql",
    "Magento_GraphQlServer": "graphql",
    "Magento_Webapi": "api",
    "Magento_WebapiAsync": "api",
    "Magento_Analytics": "analytics",
    "Magento_Authorization": "security",
    "Magento_Security": "security",
    "Magento_TwoFactorAuth": "security",
    "Magento_Store": "multi-store",
    "Magento_Directory": "multi-store",
    "Magento_Theme": "theme",
    "Magento_Swatches": "theme",
    "Magento_Cron": "cron",
}


def derive_parser_tags(dependency_names: list[str]) -> list[Tag]:
    found = {
        _DEPENDENCY_TAG_SIGNALS[name] for name in dependency_names if name in _DEPENDENCY_TAG_SIGNALS
    }
    return [Tag(name=tag, source="parser", confidence=1.0) for tag in sorted(found)]


def filter_tags(tags: list[Tag]) -> tuple[list[Tag], list[str]]:
    """Filter the raw, untrusted LLM-produced tags (doc.tags) against the
    controlled vocabulary. Never trust a tag's self-reported `source` here —
    genuine parser tags come only from derive_parser_tags() and are merged in
    separately by the caller; nothing legitimately reaches this function
    already carrying source="parser", so honoring that claim would let the
    model bypass ALLOWED_TAGS just by setting it.
    """
    kept: list[Tag] = []
    rejected: list[str] = []
    for tag in tags:
        if tag.name in ALLOWED_TAGS:
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
