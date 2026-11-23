"""ClusterFuzzLite harness for every lxml-based declarative-XML parser in
app/scanner/: these read etc/*.xml straight out of a scanned, untrusted
Magento module, so a malformed file reaching them is attacker-controlled
input, not a test fixture. Each parser's own contract is to fail open
(return [], None, or a typed exception for a handful of named cases) on
anything that isn't valid-enough XML in the expected shape -- any other
exception here is a real bug Atheris should report, not expected behavior.
"""
import atheris
import sys
import tempfile
from pathlib import Path

with atheris.instrument_imports():
    from app.scanner.acl_xml import parse_acl_xml
    from app.scanner.cache_xml import parse_cache_xml
    from app.scanner.crontab_xml import parse_crontab_xml
    from app.scanner.db_schema_xml import parse_db_schema_xml
    from app.scanner.indexer_xml import parse_indexer_xml
    from app.scanner.menu_xml import parse_menu_xml
    from app.scanner.module_xml import InvalidModuleXmlError, parse_module_xml
    from app.scanner.mview_xml import parse_mview_xml
    from app.scanner.queue_config import parse_queue_config
    from app.scanner.routes_xml import parse_routes_xml
    from app.scanner.system_xml import parse_system_xml
    from app.scanner.webapi_xml import parse_webapi_xml
    from app.scanner.widget_xml import parse_widget_xml

# parse_xml_root-based parsers (acl/cache/crontab/db_schema/indexer/menu/mview/
# queue_config/system/webapi/widget) never raise on malformed input by
# contract -- they return []/(([],[])) through parse_xml_root's own
# try/except XMLSyntaxError. module.xml and routes.xml are the two
# exceptions with their own documented failure path.
_PARSERS = [
    parse_acl_xml,
    parse_cache_xml,
    parse_crontab_xml,
    parse_db_schema_xml,
    parse_indexer_xml,
    parse_menu_xml,
    parse_mview_xml,
    parse_system_xml,
    parse_webapi_xml,
    parse_widget_xml,
]


def TestOneInput(data: bytes) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fuzz.xml"
        path.write_bytes(data)

        for parser in _PARSERS:
            parser(path)

        try:
            parse_module_xml(path)
        except InvalidModuleXmlError:
            pass

        parse_routes_xml(path, "frontend")
        parse_queue_config(path, path, path)


atheris.Setup(sys.argv, TestOneInput)
atheris.Fuzz()
