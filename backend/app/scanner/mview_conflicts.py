from collections import defaultdict
from dataclasses import dataclass

from app.scanner.dto import QualityFinding


@dataclass
class MviewRow:
    module_id: int
    module_name: str
    view_id: str


def detect_mview_conflicts(mviews: list[MviewRow]) -> list[tuple[int, QualityFinding]]:
    """Cross-module mview.xml conflicts: two or more modules declaring a
    <view> with the exact same id. Real impact, not theoretical -- Magento
    merges every installed module's mview declarations into one table by
    id, so a duplicate id is genuinely ambiguous, same risk class as a
    duplicate indexer.xml id or acl.xml resource id. The id itself is the
    whole conflict signal; same-author restatement of the identical id is
    not flagged.
    """
    groups: dict[str, list[MviewRow]] = defaultdict(list)
    for r in mviews:
        groups[r.view_id].append(r)

    findings: list[tuple[int, QualityFinding]] = []

    for view_id, group in groups.items():
        module_ids = {r.module_id for r in group}
        if len(module_ids) < 2:
            continue  # same-author overlap -- not a cross-module conflict

        who = ", ".join(sorted({r.module_name for r in group}))
        message = (
            f'Multiple modules declare the same mview.xml `<view id="{view_id}">`: {who} — '
            "Magento merges every module's mview table by id; an exact duplicate is ambiguous, "
            "with one module's declaration silently winning depending on compilation order."
        )
        for module_id in module_ids:
            findings.append(
                (
                    module_id,
                    QualityFinding(
                        check_type="view_id_conflict",
                        severity="warning",
                        file_path=None,
                        line=None,
                        message=message,
                    ),
                )
            )

    return findings
