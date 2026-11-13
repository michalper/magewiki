from pathlib import Path

from app.scanner.dto import MenuItemEntry
from app.scanner.xml_parse_utils import parse_xml_root


def parse_menu_xml(path: Path) -> list[MenuItemEntry]:
    """Parse a module's etc/adminhtml/menu.xml into structured facts --
    admin menu items Magento's menu builder keys by id. Unlike every other
    declarative-merge file this project parses, a duplicate id here isn't
    an ambiguous silent override: it's a confirmed hard Magento error
    ("Two 'add' commands cannot have equal id"). Same role lxml plays for
    di.xml/widget.xml: facts come from the parser, not the LLM.
    """
    root = parse_xml_root(path)
    if root is None:
        return []

    entries: list[MenuItemEntry] = []
    for add_el in root.findall("add"):
        menu_item_id = add_el.get("id")
        if not menu_item_id:
            continue
        entries.append(MenuItemEntry(menu_item_id=menu_item_id, title=add_el.get("title")))
    return entries
