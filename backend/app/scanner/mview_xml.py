from pathlib import Path

from app.scanner.dto import MviewEntry
from app.scanner.xml_parse_utils import parse_xml_root


def parse_mview_xml(path: Path) -> list[MviewEntry]:
    """Parse a module's etc/mview.xml into structured facts — materialized
    views a module registers (the changelog-subscription side of an
    indexer), with their backing class and group. Same role lxml plays for
    di.xml/webapi.xml: facts come from the parser, not the LLM.
    """
    root = parse_xml_root(path)
    if root is None:
        return []

    entries: list[MviewEntry] = []
    for view_el in root.findall("view"):
        view_id = view_el.get("id")
        if not view_id:
            continue
        entries.append(
            MviewEntry(
                view_id=view_id,
                class_name=view_el.get("class"),
                group_name=view_el.get("group"),
            )
        )
    return entries
