from pathlib import Path

from app.scanner.dto import EmailTemplateEntry
from app.scanner.xml_parse_utils import parse_xml_root


def parse_email_templates_xml(path: Path) -> list[EmailTemplateEntry]:
    """Parse a module's etc/email_templates.xml into structured facts --
    email template declarations Magento merges by id into one global
    namespace (not per-area, like system.xml). A duplicate id across
    modules is always either a real conflict or a content-identical no-op
    duplicate -- unlike cache.xml, there's no legitimate "same id,
    different cosmetic metadata" pattern here, since `id` is the template's
    sole merge key and the whole declaration (file/type/area) goes with it.
    Same role lxml plays for di.xml/widget.xml/menu.xml: facts come from
    the parser, not the LLM.
    """
    root = parse_xml_root(path)
    if root is None:
        return []

    entries: list[EmailTemplateEntry] = []
    for template_el in root.findall("template"):
        template_id = template_el.get("id")
        if not template_id:
            continue
        entries.append(
            EmailTemplateEntry(
                template_id=template_id,
                label=template_el.get("label"),
                file=template_el.get("file"),
                type=template_el.get("type"),
                area=template_el.get("area"),
            )
        )
    return entries
