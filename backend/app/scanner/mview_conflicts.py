from dataclasses import dataclass

from app.scanner.dto import QualityFinding
from app.scanner.duplicate_id_conflict import detect_duplicate_id_conflict


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
    return detect_duplicate_id_conflict(
        mviews,
        "view_id",
        "view_id_conflict",
        lambda view_id, who: (
            f'Multiple modules declare the same mview.xml `<view id="{view_id}">`: {who} — '
            "Magento merges every module's mview table by id; an exact duplicate is ambiguous, "
            "with one module's declaration silently winning depending on compilation order."
        ),
    )
