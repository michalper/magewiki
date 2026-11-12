from pathlib import Path

from app.scanner.dto import EventObserverEntry
from app.scanner.xml_parse_utils import parse_xml_root


def parse_events_xml(path: Path) -> list[EventObserverEntry]:
    root = parse_xml_root(path)
    if root is None:
        return []

    entries: list[EventObserverEntry] = []
    for event_el in root.findall("event"):
        event_name = event_el.get("name")
        if not event_name:
            continue
        for observer_el in event_el.findall("observer"):
            observer_name = observer_el.get("name")
            observer_class = observer_el.get("instance")
            if not observer_name or not observer_class:
                continue
            entries.append(
                EventObserverEntry(
                    event_name=event_name,
                    observer_name=observer_name,
                    observer_class=observer_class,
                    disabled=observer_el.get("disabled") == "true",
                )
            )

    return entries
