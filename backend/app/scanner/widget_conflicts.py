from collections import defaultdict
from dataclasses import dataclass

from app.scanner.dto import QualityFinding


@dataclass
class WidgetRow:
    module_id: int
    module_name: str
    widget_id: str


def detect_widget_id_conflicts(widgets: list[WidgetRow]) -> list[tuple[int, QualityFinding]]:
    """Cross-module widget.xml conflicts: two or more modules declaring a
    <widget> with the exact same id. Real impact, not theoretical -- Magento
    merges every installed module's widget declarations into one table by id
    (regardless of which view/{base,frontend,adminhtml}/widget.xml file they
    came from), so a duplicate id is genuinely ambiguous, same risk class as
    a duplicate indexer.xml id -- see indexer_conflicts.py's docstring for the
    identical reasoning. The id itself is the whole conflict signal;
    same-author restatement of the identical id is not flagged.
    """
    groups: dict[str, list[WidgetRow]] = defaultdict(list)
    for r in widgets:
        groups[r.widget_id].append(r)

    findings: list[tuple[int, QualityFinding]] = []

    for widget_id, group in groups.items():
        module_ids = {r.module_id for r in group}
        if len(module_ids) < 2:
            continue  # same-author overlap -- not a cross-module conflict

        who = ", ".join(sorted({r.module_name for r in group}))
        message = (
            f'Multiple modules declare the same widget.xml `<widget id="{widget_id}">`: {who} — '
            "Magento merges every module's widget table by id; an exact duplicate is ambiguous, "
            "with one module's declaration silently winning depending on compilation order."
        )
        for module_id in module_ids:
            findings.append(
                (
                    module_id,
                    QualityFinding(
                        check_type="widget_id_conflict",
                        severity="warning",
                        file_path=None,
                        line=None,
                        message=message,
                    ),
                )
            )

    return findings
