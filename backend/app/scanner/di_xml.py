from pathlib import Path

from app.scanner.dto import DiPluginEntry, DiPreferenceEntry, DiVirtualTypeEntry, DiXmlResult
from app.scanner.xml_parse_utils import parse_xml_root


def parse_di_xml(path: Path) -> DiXmlResult:
    root = parse_xml_root(path)
    if root is None:
        return DiXmlResult()

    preferences = [
        DiPreferenceEntry(for_type=for_type, preference_type=preference_type)
        for el in root.findall("preference")
        if (for_type := el.get("for")) and (preference_type := el.get("type"))
    ]

    # <virtualType name="X" type="Y"> composes a new "class" from an existing
    # one with different constructor arguments — a very common pattern (UI
    # Component data providers, collections with preset filters) that was
    # previously invisible: only <preference>/<plugin> were parsed from this
    # same file.
    virtual_types = [
        DiVirtualTypeEntry(name=name, virtual_type=virtual_type)
        for el in root.findall("virtualType")
        if (name := el.get("name")) and (virtual_type := el.get("type"))
    ]

    plugins: list[DiPluginEntry] = []
    for type_el in root.findall(".//type"):
        intercepted_type = type_el.get("name")
        if not intercepted_type:
            continue
        for plugin_el in type_el.findall("plugin"):
            plugin_name = plugin_el.get("name")
            plugin_class = plugin_el.get("type")
            if not plugin_name or not plugin_class:
                continue
            sort_order_raw = plugin_el.get("sortOrder")
            plugins.append(
                DiPluginEntry(
                    intercepted_type=intercepted_type,
                    plugin_name=plugin_name,
                    plugin_class=plugin_class,
                    sort_order=int(sort_order_raw) if sort_order_raw else None,
                    disabled=plugin_el.get("disabled") == "true",
                )
            )

    return DiXmlResult(preferences=preferences, plugins=plugins, virtual_types=virtual_types)
