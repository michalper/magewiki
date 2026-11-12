from pathlib import Path

from lxml import etree

from app.scanner.dto import IndexerEntry


def parse_indexer_xml(path: Path) -> list[IndexerEntry]:
    """Parse a module's etc/indexer.xml into structured facts — indexer
    processes a module registers, with their view_id (links to mview.xml)
    and backing class. Same role lxml plays for di.xml/webapi.xml: facts
    come from the parser, not the LLM.
    """
    if not path.is_file():
        return []

    try:
        root = etree.parse(str(path)).getroot()
    except etree.XMLSyntaxError:
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
