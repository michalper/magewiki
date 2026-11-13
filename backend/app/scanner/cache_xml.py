from pathlib import Path

from app.scanner.dto import CacheTypeEntry
from app.scanner.xml_parse_utils import parse_xml_root


def parse_cache_xml(path: Path) -> list[CacheTypeEntry]:
    """Parse a module's etc/cache.xml into structured facts -- cache type
    declarations Magento merges by name (root-level, not per-area, unlike
    system.xml). Unlike menu.xml/widget.xml, a same-name re-declaration is
    a real, intentional pattern (a module legitimately overriding a core
    cache type's attributes), so this parser only captures the facts;
    cache_type_conflicts.py decides whether a given overlap is a genuine
    disagreement. Same role lxml plays for di.xml/indexer.xml: facts come
    from the parser, not the LLM.
    """
    root = parse_xml_root(path)
    if root is None:
        return []

    entries: list[CacheTypeEntry] = []
    for type_el in root.findall("type"):
        cache_type_id = type_el.get("name")
        if not cache_type_id:
            continue
        entries.append(CacheTypeEntry(cache_type_id=cache_type_id, instance=type_el.get("instance")))
    return entries
