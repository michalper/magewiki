from dataclasses import dataclass

from app.scanner.dto import QualityFinding
from app.scanner.duplicate_id_conflict import detect_duplicate_id_conflict


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
    return detect_duplicate_id_conflict(
        resources,
        "resource_id",
        "acl_resource_conflict",
        lambda resource_id, who: (
            f'Multiple modules declare the same acl.xml `<resource id="{resource_id}">`: {who} — '
            "Magento merges every module's ACL resource tree by id; an exact duplicate is ambiguous, "
            "with one module's declaration silently winning depending on compilation order."
        ),
    )
