from pathlib import Path

from app.scanner.dto import IndexerEntry
from app.scanner.xml_parse_utils import parse_xml_root


def parse_indexer_xml(path: Path) -> list[IndexerEntry]:
    """Parse a module's etc/indexer.xml into structured facts — indexer
    processes a module registers, with their own view_id attribute (no
    check in this codebase currently cross-references it against
    mview.xml's own view ids) and backing class. Same role lxml plays for
    di.xml/webapi.xml: facts come from the parser, not the LLM.
    """
    root = parse_xml_root(path)
    if root is None:
        return []

    entries: list[IndexerEntry] = []
    for indexer_el in root.findall("indexer"):
        indexer_id = indexer_el.get("id")
        if not indexer_id:
            continue
        entries.append(
            IndexerEntry(
                indexer_id=indexer_id,
                view_id=indexer_el.get("view_id"),
                class_name=indexer_el.get("class"),
            )
        )
    return entries
