from pathlib import Path

from app.scanner.db_schema_xml import parse_db_schema_xml

_DB_SCHEMA_XML = """<?xml version="1.0"?>
<schema xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="urn:magento:framework:Setup/Declaration/Schema/etc/schema.xsd">
    <table name="vendor_module_sample" resource="default" engine="innodb" comment="Sample table">
        <column xsi:type="int" name="entity_id" nullable="false" identity="true" comment="Entity ID"/>
        <column xsi:type="varchar" name="name" nullable="false" length="255" comment="Name"/>
        <constraint xsi:type="primary" referenceId="PRIMARY">
            <column name="entity_id"/>
        </constraint>
    </table>
</schema>
"""


def test_parse_db_schema_xml(tmp_path: Path):
    path = tmp_path / "db_schema.xml"
    path.write_text(_DB_SCHEMA_XML, encoding="utf-8")

    tables = parse_db_schema_xml(path)

    assert len(tables) == 1
    table = tables[0]
    assert table.table_name == "vendor_module_sample"
    assert table.comment == "Sample table"
    assert table.column_count == 2


def test_parse_db_schema_xml_missing_file(tmp_path: Path):
    assert parse_db_schema_xml(tmp_path / "db_schema.xml") == []


def test_parse_db_schema_xml_malformed_xml(tmp_path: Path):
    path = tmp_path / "db_schema.xml"
    path.write_text("<schema><unclosed>", encoding="utf-8")
    assert parse_db_schema_xml(path) == []


def test_parse_db_schema_xml_skips_a_table_without_a_name(tmp_path: Path):
    path = tmp_path / "db_schema.xml"
    path.write_text('<?xml version="1.0"?>\n<schema><table comment="no name"/></schema>', encoding="utf-8")
    assert parse_db_schema_xml(path) == []
