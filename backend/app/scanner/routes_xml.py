from pathlib import Path

from app.scanner.dto import RouteEntry
from app.scanner.xml_parse_utils import parse_xml_root


def parse_routes_xml(path: Path, area: str) -> list[RouteEntry]:
    """Parse a module's etc/frontend/routes.xml or etc/adminhtml/routes.xml
    into structured facts — the URL route id/frontName a module registers
    for that area. Real shape:
    <config><router id="standard"><route id="..." frontName="..."><module
    name="..." /></route></router></config> — which area a given file
    belongs to isn't in the file itself, only in which of the two paths it
    was read from, so the caller passes `area` explicitly rather than this
    parser guessing it from the path. Same role lxml plays for di.xml/
    webapi.xml: facts come from the parser, not the LLM.
    """
    root = parse_xml_root(path)
    if root is None:
        return []

    # Descendant search (".//route"), not a fixed <router>/<route> path --
    # same defensiveness as system_xml.py's ".//section" and acl_xml.py's
    # ".//resources", in case a future routes.xsd revision changes the
    # <router> wrapper depth.
    entries: list[RouteEntry] = []
    for route_el in root.findall(".//route"):
        route_id = route_el.get("id")
        front_name = route_el.get("frontName")
        if not route_id or not front_name:
            continue
        entries.append(RouteEntry(area=area, route_id=route_id, front_name=front_name))
    return entries
