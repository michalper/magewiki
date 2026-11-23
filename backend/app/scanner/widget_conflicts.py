from dataclasses import dataclass

from app.scanner.dto import QualityFinding
from app.scanner.duplicate_id_conflict import detect_duplicate_id_conflict


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
    return detect_duplicate_id_conflict(
        widgets,
        "widget_id",
        "widget_id_conflict",
        lambda widget_id, who: (
            f'Multiple modules declare the same widget.xml `<widget id="{widget_id}">`: {who} — '
            "Magento merges every module's widget table by id; an exact duplicate is ambiguous, "
            "with one module's declaration silently winning depending on compilation order."
        ),
    )
