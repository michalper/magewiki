from pathlib import Path

from lxml import etree

from app.scanner.dto import DbColumnEntry, DbTableEntry

_BOOL_ATTRS = {"true": True, "false": False}


def parse_db_schema_xml(path: Path) -> tuple[list[DbTableEntry], list[DbColumnEntry]]:
    """Parse a module's etc/db_schema.xml into structured facts — database tables a
    module declares (comment and column count), plus one flat entry per column
    (name, type, nullable) — a later extension of the original table-level-only
    scope, added so a column-level cross-module conflict (two modules disagreeing
    on the same table's same column) can be detected; still not a full
    column-by-column breakdown (length/identity/default aren't captured, since
    nothing needs them yet). Same role lxml plays for di.xml/events.xml: facts
    come from the parser, not the LLM.
    """
    if not path.is_file():
        return [], []

    try:
        root = etree.parse(str(path)).getroot()
    except etree.XMLSyntaxError:
        return [], []

    tables: list[DbTableEntry] = []
    columns: list[DbColumnEntry] = []
    for table_el in root.findall("table"):
        table_name = table_el.get("name")
        if not table_name:
            continue
        column_els = table_el.findall("column")
        tables.append(
            DbTableEntry(
                table_name=table_name,
                comment=table_el.get("comment"),
                column_count=len(column_els),
            )
        )
        for column_el in column_els:
            column_name = column_el.get("name")
            xsi_type = column_el.get("{http://www.w3.org/2001/XMLSchema-instance}type")
            if not column_name or not xsi_type:
                continue
            columns.append(
                DbColumnEntry(
                    table_name=table_name,
                    column_name=column_name,
                    xsi_type=xsi_type,
                    nullable=_BOOL_ATTRS.get(column_el.get("nullable", "")),
                )
            )
    return tables, columns
