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
    name = module_el.get("name") if module_el is not None else None
    if module_el is None or not name:
        raise InvalidModuleXmlError("module.xml has no <module name=...>")

    sequence = [
        seq_name
        for el in module_el.findall("sequence/module")
        if (seq_name := el.get("name"))
    ]

    return ModuleXmlResult(
        name=name,
        setup_version=module_el.get("setup_version"),
        sequence=sequence,
    )
