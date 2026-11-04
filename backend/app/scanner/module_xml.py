from pathlib import Path

from lxml import etree

from app.scanner.dto import ModuleXmlResult


class InvalidModuleXmlError(Exception):
    pass


def parse_module_xml(path: Path) -> ModuleXmlResult:
    try:
        tree = etree.parse(str(path))
    except etree.XMLSyntaxError as exc:
        raise InvalidModuleXmlError(f"malformed module.xml: {exc}") from exc

    module_el = tree.getroot().find("module")
    if module_el is None or not module_el.get("name"):
        raise InvalidModuleXmlError("module.xml has no <module name=...>")

    sequence = [
        el.get("name")
        for el in module_el.findall("sequence/module")
        if el.get("name")
    ]

    return ModuleXmlResult(
        name=module_el.get("name"),
        setup_version=module_el.get("setup_version"),
        sequence=sequence,
    )
