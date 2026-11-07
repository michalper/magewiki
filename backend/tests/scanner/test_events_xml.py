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


def test_parse_events_xml_malformed_xml(tmp_path: Path):
    path = tmp_path / "events.xml"
    path.write_text("<config><unclosed>", encoding="utf-8")
    assert parse_events_xml(path) == []


def test_parse_events_xml_skips_an_event_without_a_name_and_an_observer_missing_attributes(tmp_path: Path):
    path = tmp_path / "events.xml"
    path.write_text(
        '<?xml version="1.0"?>\n'
        "<config>"
        '<event><observer name="x" instance="Vendor\\Module\\Observer\\X"/></event>'
        '<event name="real_event"><observer instance="NoNameAttr"/></event>'
        "</config>",
        encoding="utf-8",
    )
    assert parse_events_xml(path) == []
