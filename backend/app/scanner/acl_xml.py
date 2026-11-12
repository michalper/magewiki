from pathlib import Path

from lxml import etree

from app.scanner.dto import AclResourceEntry


def _walk_resources(resource_el, parent_id: str | None, out: list[AclResourceEntry]) -> None:
    resource_id = resource_el.get("id")
    if resource_id:
        out.append(AclResourceEntry(resource_id=resource_id, title=resource_el.get("title"), parent_id=parent_id))
    for child in resource_el.findall("resource"):
        _walk_resources(child, resource_id, out)


def parse_acl_xml(path: Path) -> list[AclResourceEntry]:
    """Parse a module's etc/acl.xml into structured facts — the admin ACL
    resource tree it declares. Same role lxml plays for di.xml/webapi.xml:
    facts come from the parser, not the LLM.

    `<resource>` elements nest arbitrarily (a resource's children are its own
    sub-resources) — walked recursively and flattened to one entry per
    resource, each carrying its immediate parent's id (or None for a
    top-level resource). The nesting itself isn't needed by anything
    downstream yet (the acl_resource_conflict check only needs
    (resource_id, module_id) pairs), but parent_id is kept since it's free
    and may be useful for citations later.
    """
    if not path.is_file():
        return []

    try:
        root = etree.parse(str(path)).getroot()
    except etree.XMLSyntaxError:
        return []

    # Real shape: <config><acl><resources><resource id="..."/></resources></acl></config>
    # -- found via a descendant search (".//") rather than a fixed path, same
    # defensiveness as system_xml.py's ".//section", so this doesn't silently
    # return nothing if a future acl.xsd revision changes the wrapper depth.
    resources_el = root.find(".//resources")
    if resources_el is None:
        return []

    entries: list[AclResourceEntry] = []
    for resource_el in resources_el.findall("resource"):
        _walk_resources(resource_el, None, entries)
    return entries
