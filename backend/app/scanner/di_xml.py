from pathlib import Path

from lxml import etree

from app.scanner.dto import DiPluginEntry, DiPreferenceEntry, DiXmlResult


def parse_di_xml(path: Path) -> DiXmlResult:
    if not path.is_file():
        return DiXmlResult()

    try:
        root = etree.parse(str(path)).getroot()
    except etree.XMLSyntaxError:
        return DiXmlResult()

    preferences = [
        DiPreferenceEntry(for_type=for_type, preference_type=preference_type)
        for el in root.findall("preference")
        if (for_type := el.get("for")) and (preference_type := el.get("type"))
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

    return DiXmlResult(preferences=preferences, plugins=plugins)
