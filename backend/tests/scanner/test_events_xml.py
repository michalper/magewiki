from pathlib import Path

from app.scanner.events_xml import parse_events_xml


def test_parse_events_xml(demo_module_path: Path):
    entries = parse_events_xml(demo_module_path / "etc" / "events.xml")

    assert len(entries) == 1
    entry = entries[0]
    assert entry.event_name == "sales_order_place_after"
    assert entry.observer_class == "Vendor\\Module\\Observer\\SampleOrderObserver"
    assert entry.disabled is False


def test_parse_events_xml_missing_file(tmp_path: Path):
    assert parse_events_xml(tmp_path / "events.xml") == []
