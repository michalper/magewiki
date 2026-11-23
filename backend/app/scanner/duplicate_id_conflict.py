from collections import defaultdict
from collections.abc import Callable
from typing import Any

from app.scanner.dto import QualityFinding


def detect_duplicate_id_conflict(
    rows: list[Any],
    id_attr: str,
    check_type: str,
    message: Callable[[str, str], str],
) -> list[tuple[int, QualityFinding]]:
    """Shared algorithm behind every "two or more modules declare the same
    <X id=...>" cross-module conflict check (acl/indexer/mview/widget/menu) --
    Magento merges each of these into one global-by-id table/tree/menu, so an
    exact id collision across modules is genuinely ambiguous (or, for
    menu.xml, a confirmed hard compile-time error -- still flagged the same
    way; the exact wording is each caller's own `message`). Same-author
    restatement of the identical id (every matching row from one module) is
    not flagged, only a real cross-module collision.

    Extracted after a whole-project code review found 5 call sites had
    copied this exact algorithm byte-for-byte, differing only in the row's
    id field name, the check_type, and the message text -- each of those 5
    now just supplies `id_attr`/`check_type`/`message` and keeps its own
    dataclass, public function name, and docstring unchanged.

    `rows` elements only need a `.module_id: int`, a `.module_name: str`,
    and whatever string attribute `id_attr` names (not a shared base class,
    since each caller's dataclass -- IndexerRow, MviewRow, WidgetRow,
    MenuItemRow, AclResourceRow -- is constructed positionally from a raw DB
    row in orchestrator.py and names its id field differently on purpose,
    for clarity at each of those call sites).
    """
    groups: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        groups[getattr(row, id_attr)].append(row)

    findings: list[tuple[int, QualityFinding]] = []
    for id_value, group in groups.items():
        module_ids = {row.module_id for row in group}
        if len(module_ids) < 2:
            continue  # same-author overlap -- not a cross-module conflict

        who = ", ".join(sorted({row.module_name for row in group}))
        finding_message = message(id_value, who)
        for module_id in module_ids:
            findings.append(
                (
                    module_id,
                    QualityFinding(
                        check_type=check_type,
                        severity="warning",
                        file_path=None,
                        line=None,
                        message=finding_message,
                    ),
                )
            )

    return findings
