from pathlib import Path

from lxml import etree

from app.scanner.dto import WebapiRouteEntry


def parse_webapi_xml(path: Path) -> list[WebapiRouteEntry]:
    """Parse a module's etc/webapi.xml into structured facts — REST endpoints a
    module exposes, with their backing service class/method and ACL resource. Same
    role lxml plays for di.xml/events.xml: facts come from the parser, not the LLM.
    """
    if not path.is_file():
        return []

    try:
        root = etree.parse(str(path)).getroot()
    except etree.XMLSyntaxError:
        return []

    routes: list[WebapiRouteEntry] = []
    for route_el in root.findall("route"):
        url = route_el.get("url")
        http_method = route_el.get("method")
        service_el = route_el.find("service")
        if not url or not http_method or service_el is None:
            continue
        service_class = service_el.get("class")
        service_method = service_el.get("method")
        if not service_class or not service_method:
            continue
        resource_el = route_el.find("resources/resource")
        routes.append(
            WebapiRouteEntry(
                url=url,
                http_method=http_method,
                service_class=service_class,
                service_method=service_method,
                acl_resource=resource_el.get("ref") if resource_el is not None else None,
            )
        )
    return routes
