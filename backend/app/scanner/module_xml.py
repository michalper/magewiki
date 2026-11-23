from pathlib import Path

from lxml import etree

from app.scanner.discovery import is_safe_to_read
from app.scanner.dto import ModuleXmlResult
from app.scanner.xml_parse_utils import HARDENED_XML_PARSER


class InvalidModuleXmlError(Exception):
    pass


def parse_module_xml(path: Path) -> ModuleXmlResult:
    if not is_safe_to_read(path):
        raise InvalidModuleXmlError(f"{path} is a symlink, refusing to follow it")

    try:
        tree = etree.parse(str(path), parser=HARDENED_XML_PARSER)
    except (etree.XMLSyntaxError, OSError) as exc:
        # lxml raises OSError, not XMLSyntaxError, for some malformed
        # encoding declarations when parsing from a file path -- found by
        # fuzzing xml_parse_utils.parse_xml_root's identical etree.parse
        # call, not by any hand-written XML sample.
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
