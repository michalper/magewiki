from collections import defaultdict
from dataclasses import dataclass

from app.scanner.dto import QualityFinding


@dataclass
class GraphQlFieldRow:
    module_id: int
    module_name: str
    operation_type: str
    type_name: str
    field_name: str
    resolver_class: str | None


def detect_graphql_field_conflicts(fields: list[GraphQlFieldRow]) -> list[tuple[int, QualityFinding]]:
    """Cross-module schema.graphqls conflicts: two or more modules declaring the
    same field on the same type (e.g. both adding `Query.customField` or both
    extending `ProductInterface.custom_field`). Real impact, not theoretical —
    Magento's GraphQL schema reader merges every module's type extensions
    together at compile time; an exact duplicate field name on the same type
    is ambiguous (depending on which module's resolver actually ends up wired
    for a request, or a schema-build error, neither of which is a documented,
    deliberate override mechanism the way a resolver interface override
    normally works).

    Same "flag a concrete, certain conflict" pragmatism as the rest of this
    family: two modules declaring the exact same field with the exact same
    resolver (e.g. one module's schema.graphqls restating a shared base
    field verbatim) is not flagged, only a genuine disagreement about which
    resolver actually backs the field.
    """
    groups: dict[tuple[str, str, str], list[GraphQlFieldRow]] = defaultdict(list)
    for f in fields:
        groups[(f.operation_type, f.type_name, f.field_name)].append(f)

    findings: list[tuple[int, QualityFinding]] = []

    for (operation_type, type_name, field_name), group in groups.items():
        module_ids = {f.module_id for f in group}
        if len(module_ids) < 2:
            continue  # same-author overlap -- not a cross-module conflict

        distinct_resolvers = {f.resolver_class for f in group}
        if len(distinct_resolvers) < 2:
            continue  # every module agrees on the same (or no) resolver -- not a conflict

        who = ", ".join(sorted({f"{f.module_name} -> {f.resolver_class or 'no resolver'}" for f in group}))
        message = (
            f"Multiple modules declare the GraphQL field `{type_name}.{field_name}` "
            f"(operation `{operation_type}`): {who} — Magento merges every module's schema.graphqls "
            "type extensions together; which resolver actually backs this field is ambiguous."
        )
        for module_id in module_ids:
            findings.append(
                (
                    module_id,
                    QualityFinding(
                        check_type="graphql_field_conflict",
                        severity="warning",
                        file_path=None,
                        line=None,
                        message=message,
                    ),
                )
            )

    return findings
