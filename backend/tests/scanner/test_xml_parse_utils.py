from pathlib import Path

from app.scanner.xml_parse_utils import parse_xml_root


def test_parse_xml_root_returns_the_root_element(tmp_path: Path):
    xml = tmp_path / "di.xml"
    xml.write_text('<?xml version="1.0"?><config><preference for="A" type="B"/></config>')

    root = parse_xml_root(xml)

    assert root.tag == "config"


def test_parse_xml_root_returns_none_for_a_missing_file(tmp_path: Path):
    assert parse_xml_root(tmp_path / "does-not-exist.xml") is None


def test_parse_xml_root_returns_none_for_malformed_xml(tmp_path: Path):
    xml = tmp_path / "di.xml"
    xml.write_text("<config><unclosed>")

    assert parse_xml_root(xml) is None


def test_parse_xml_root_returns_none_for_invalid_bytes_in_the_declared_encoding(tmp_path: Path):
    """Regression found by fuzzing (.clusterfuzzlite/fuzz_xml_parsers.py), not by
    any hand-written sample: lxml raises OSError, not XMLSyntaxError, for some
    byte sequences that don't decode under the file's own declared encoding
    (parsing from a file path, not from a string/bytes buffer) -- the generic
    "malformed XML" case every other test here covers via XMLSyntaxError alone
    didn't catch this one until it was fixed."""
    xml = tmp_path / "di.xml"
    xml.write_bytes(b'<?xml version="1.0" encoding="UTF-8"?><config>\xff\xfe</config>')

    assert parse_xml_root(xml) is None


def test_parse_xml_root_does_not_expand_an_xxe_entity(tmp_path: Path):
    """Defense-in-depth regression for HARDENED_XML_PARSER (see its own
    comment in xml_parse_utils.py: checked directly, this was never
    exploitable against the pinned lxml/libxml2, but the parser is hardened
    explicitly anyway). Verified against a real local file (not a mock)
    outside the module directory -- its content must never appear anywhere
    in, or leak via, the parse result, regardless of which layer is doing
    the blocking."""
    secret = tmp_path.parent / "xxe_secret.txt"
    secret.write_text("super-secret-host-content")
    xml = tmp_path / "di.xml"
    xml.write_text(
        '<?xml version="1.0"?>'
        f'<!DOCTYPE config [ <!ENTITY xxe SYSTEM "file://{secret}"> ]>'
        "<config><preference for=\"A\" type=\"&xxe;\"/></config>"
    )

    assert parse_xml_root(xml) is None


def test_parse_xml_root_returns_none_for_a_symlink(tmp_path: Path):
    """Security regression, shared by all 14 of this helper's callers
    (acl/cache/crontab/di/events/system/webapi/db_schema/indexer/menu/
    mview/routes/widget/queue_config xml) -- a symlinked declarative-XML
    file must never have its target's content parsed (a real symlink to a
    file outside the module root, not a mock)."""
    outside = tmp_path.parent / "outside_di.xml"
    outside.write_text('<?xml version="1.0"?><config><preference for="A" type="B"/></config>')
    link = tmp_path / "di.xml"
    link.symlink_to(outside)

    assert parse_xml_root(link) is None
