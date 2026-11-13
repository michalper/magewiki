from pathlib import Path

from app.scanner.dto import WidgetEntry
from app.scanner.xml_parse_utils import parse_xml_root


def parse_widget_xml(path: Path) -> list[WidgetEntry]:
    """Parse a module's view/{base,frontend,adminhtml}/widget.xml into
    structured facts -- widget declarations Magento merges into one global
    id namespace regardless of which view dir they came from (unlike
    routes.xml, there's no per-area uniqueness constraint here). Same role
    lxml plays for di.xml/indexer.xml: facts come from the parser, not the
    LLM.
    """
    root = parse_xml_root(path)
    if root is None:
        return []

    entries: list[WidgetEntry] = []
    for widget_el in root.findall("widget"):
        widget_id = widget_el.get("id")
        class_name = widget_el.get("class")
        if not widget_id or not class_name:
            continue
        entries.append(WidgetEntry(widget_id=widget_id, class_name=class_name))
    return entries
