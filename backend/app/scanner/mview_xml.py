from pathlib import Path

from lxml import etree

from app.scanner.dto import MviewEntry


def parse_mview_xml(path: Path) -> list[MviewEntry]:
    """Parse a module's etc/mview.xml into structured facts — materialized
    views a module registers (the changelog-subscription side of an
    indexer), with their backing class and group. Same role lxml plays for
    di.xml/webapi.xml: facts come from the parser, not the LLM.
    """
    if not path.is_file():
        return []

    try:
        root = etree.parse(str(path)).getroot()
    except etree.XMLSyntaxError:
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
