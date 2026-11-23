from dataclasses import dataclass

from app.scanner.dto import QualityFinding
from app.scanner.duplicate_id_conflict import detect_duplicate_id_conflict


@dataclass
class IndexerRow:
    module_id: int
    module_name: str
    indexer_id: str


def detect_indexer_conflicts(indexers: list[IndexerRow]) -> list[tuple[int, QualityFinding]]:
    """Cross-module indexer.xml conflicts: two or more modules declaring an
    <indexer> with the exact same id. Real impact, not theoretical --
    Magento merges every installed module's indexer declarations into one
    table by id, so a duplicate id is genuinely ambiguous, same risk class
    as a duplicate acl.xml resource id or webapi.xml route -- see
    webapi_conflicts.py's docstring for the identical reasoning. The id
    itself is the whole conflict signal; same-author restatement of the
    identical id is not flagged.
    """
    return detect_duplicate_id_conflict(
        indexers,
        "indexer_id",
        "indexer_id_conflict",
        lambda indexer_id, who: (
            f'Multiple modules declare the same indexer.xml `<indexer id="{indexer_id}">`: {who} — '
            "Magento merges every module's indexer table by id; an exact duplicate is ambiguous, "
            "with one module's declaration silently winning depending on compilation order."
        ),
    )
