from collections import defaultdict
from dataclasses import dataclass

from app.scanner.dto import QualityFinding


@dataclass
class AclResourceRow:
    module_id: int
    module_name: str
    resource_id: str


def detect_acl_resource_conflicts(resources: list[AclResourceRow]) -> list[tuple[int, QualityFinding]]:
    """Cross-module acl.xml conflicts: two or more modules declaring a
    <resource> with the exact same id. Real impact, not theoretical --
    Magento merges every installed module's ACL resource tree into one by
    id, so a duplicate id is genuinely ambiguous, same risk class as a
    duplicate webapi.xml route -- see webapi_conflicts.py's docstring for
    the identical reasoning. The id itself is the whole conflict signal
    (unlike db_schema_conflicts.py, there's no secondary attribute like
    xsi:type/nullable to compare); same-author restatement of the identical
    id is not flagged.
    """
    groups: dict[str, list[AclResourceRow]] = defaultdict(list)
    for r in resources:
        groups[r.resource_id].append(r)

    findings: list[tuple[int, QualityFinding]] = []

    for resource_id, group in groups.items():
        module_ids = {r.module_id for r in group}
        if len(module_ids) < 2:
            continue  # same-author overlap -- not a cross-module conflict

        who = ", ".join(sorted({r.module_name for r in group}))
        message = (
            f'Multiple modules declare the same acl.xml `<resource id="{resource_id}">`: {who} — '
            "Magento merges every module's ACL resource tree by id; an exact duplicate is ambiguous, "
            "with one module's declaration silently winning depending on compilation order."
        )
        for module_id in module_ids:
            findings.append(
                (
                    module_id,
                    QualityFinding(
                        check_type="acl_resource_conflict",
                        severity="warning",
                        file_path=None,
                        line=None,
                        message=message,
                    ),
                )
            )

    return findings
