from pathlib import Path

from lxml import etree

from app.scanner.dto import DbTableEntry


def parse_db_schema_xml(path: Path) -> list[DbTableEntry]:
    """Parse a module's etc/db_schema.xml into structured facts — database tables a
    module declares, with their comment and column count. Scope: table-level facts
    (name/comment/column count) as the first iteration, not a full column-by-column
    breakdown — already a real, parser-sourced fact for synthesis, and a column
    child table is a natural later extension if ever needed. Same role lxml plays
    for di.xml/events.xml: facts come from the parser, not the LLM.
    """
    if not path.is_file():
        return []

    try:
        root = etree.parse(str(path)).getroot()
    except etree.XMLSyntaxError:
        return []

    tables: list[DbTableEntry] = []
    for table_el in root.findall("table"):
        table_name = table_el.get("name")
        if not table_name:
            continue
        tables.append(
            DbTableEntry(
                table_name=table_name,
                comment=table_el.get("comment"),
                column_count=len(table_el.findall("column")),
            )
        )
    return tables
