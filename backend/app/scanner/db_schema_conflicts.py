from collections import defaultdict
from dataclasses import dataclass

from app.scanner.dto import QualityFinding


@dataclass
class DbColumnRow:
    module_id: int
    module_name: str
    table_name: str
    column_name: str
    xsi_type: str
    nullable: bool | None


def detect_db_schema_conflicts(columns: list[DbColumnRow]) -> list[tuple[int, QualityFinding]]:
    """Cross-module db_schema.xml conflicts: two or more modules declaring the
    same (table_name, column_name) with a different xsi:type or a different
    nullable value. Real impact, not theoretical: Magento's declarative schema
    merges every installed module's db_schema.xml by table/column name into one
    final definition, applied in module-sequence order — a genuine type or
    nullability disagreement between two modules means one module's definition
    silently wins and the other module's own assumption about that column
    (e.g. that it's nullable, or an int rather than a varchar) can be wrong at
    runtime, not a documented, deterministic override the way db_schema.xml
    normally resolves same-table additions.

    Deliberately conservative, same "flag a concrete, certain conflict"
    pragmatism as plugin_conflicts.py/composer_conflicts.py/webapi_conflicts.py:
    only xsi:type and nullable are compared (not length/identity/default, which
    aren't even parsed), since those two are what every db_schema.xml column
    must declare and a mismatch on either is unambiguous.
    """
    groups: dict[tuple[str, str], list[DbColumnRow]] = defaultdict(list)
    for c in columns:
        groups[(c.table_name, c.column_name)].append(c)

    findings: list[tuple[int, QualityFinding]] = []

    for (table_name, column_name), group in groups.items():
        module_ids = {c.module_id for c in group}
        if len(module_ids) < 2:
            continue  # same-author overlap -- not a cross-module conflict

        distinct_types = {c.xsi_type for c in group}
        distinct_nullable = {c.nullable for c in group}
        if len(distinct_types) < 2 and len(distinct_nullable) < 2:
            continue  # same shape declared by multiple modules -- not a conflict

        who = ", ".join(sorted({f"{c.module_name} ({c.xsi_type}, nullable={c.nullable})" for c in group}))
        reason = []
        if len(distinct_types) >= 2:
            reason.append("a different xsi:type")
        if len(distinct_nullable) >= 2:
            reason.append("a different nullable value")
        message = (
            f"Multiple modules declare `{table_name}.{column_name}` with {' and '.join(reason)}: {who} — "
            "Magento's declarative schema merges modules by sequence order; one module's definition "
            "silently wins and the other module's own assumption about this column can be wrong."
        )
        for module_id in module_ids:
            findings.append(
                (
                    module_id,
                    QualityFinding(
                        check_type="db_schema_conflict",
                        severity="warning",
                        file_path=None,
                        line=None,
                        message=message,
                    ),
                )
            )

    return findings
