from collections import defaultdict
from dataclasses import dataclass

from app.scanner.dto import QualityFinding


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
    groups: dict[str, list[IndexerRow]] = defaultdict(list)
    for r in indexers:
        groups[r.indexer_id].append(r)

    findings: list[tuple[int, QualityFinding]] = []

    for indexer_id, group in groups.items():
        module_ids = {r.module_id for r in group}
        if len(module_ids) < 2:
            continue  # same-author overlap -- not a cross-module conflict

        who = ", ".join(sorted({r.module_name for r in group}))
        message = (
            f'Multiple modules declare the same indexer.xml `<indexer id="{indexer_id}">`: {who} — '
            "Magento merges every module's indexer table by id; an exact duplicate is ambiguous, "
            "with one module's declaration silently winning depending on compilation order."
        )
        for module_id in module_ids:
            findings.append(
                (
                    module_id,
                    QualityFinding(
                        check_type="indexer_id_conflict",
                        severity="warning",
                        file_path=None,
                        line=None,
                        message=message,
                    ),
                )
            )

    return findings
