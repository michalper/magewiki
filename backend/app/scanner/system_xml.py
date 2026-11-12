from pathlib import Path

from app.scanner.dto import ConfigFieldEntry
from app.scanner.xml_parse_utils import parse_xml_root


def parse_system_xml(path: Path) -> list[ConfigFieldEntry]:
    """Parse a module's etc/adminhtml/system.xml into structured facts — admin
    config fields a module adds, each with the full section/group/field path used
    by scopeConfig->getValue() in PHP. Closes what the synthesis prompt previously
    asked the LLM to guess ("system.xml-style configuration keys evident from the
    facts above") with a real, parsed fact. Same role lxml plays for di.xml/
    events.xml: facts come from the parser, not the LLM.
    """
    root = parse_xml_root(path)
    if root is None:
        return []

    fields: list[ConfigFieldEntry] = []
    for section_el in root.findall(".//section"):
        section_id = section_el.get("id")
        if not section_id:
            continue
        for group_el in section_el.findall("group"):
            group_id = group_el.get("id")
            if not group_id:
                continue
            for field_el in group_el.findall("field"):
                field_id = field_el.get("id")
                if not field_id:
                    continue
                label_el = field_el.find("label")
                fields.append(
                    ConfigFieldEntry(
                        section_id=section_id,
                        group_id=group_id,
                        field_id=field_id,
                        label=label_el.text.strip() if label_el is not None and label_el.text else None,
                        field_type=field_el.get("type"),
                    )
                )
    return fields
