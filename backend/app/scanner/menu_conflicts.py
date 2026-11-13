from collections import defaultdict
from dataclasses import dataclass

from app.scanner.dto import QualityFinding


@dataclass
class MenuItemRow:
    module_id: int
    module_name: str
    menu_item_id: str


def detect_menu_item_id_conflicts(items: list[MenuItemRow]) -> list[tuple[int, QualityFinding]]:
    """Cross-module menu.xml conflicts: two or more modules declaring an
    admin menu `<add>` with the exact same id. Unlike every other check in
    this family, this isn't an ambiguous silent override -- it's a
    confirmed hard Magento error ("Two 'add' commands cannot have equal
    id"), thrown at compile/install time. Kept severity `warning` anyway,
    for consistency with the rest of the cross-module-conflict family --
    circular_dependency is also a guaranteed break and was deliberately
    kept `warning` for the same reason (this family has no `blocking` gate
    concept of its own). The id itself is the whole conflict signal;
    same-author restatement of the identical id is not flagged.
    """
    groups: dict[str, list[MenuItemRow]] = defaultdict(list)
    for r in items:
        groups[r.menu_item_id].append(r)

    findings: list[tuple[int, QualityFinding]] = []

    for menu_item_id, group in groups.items():
        module_ids = {r.module_id for r in group}
        if len(module_ids) < 2:
            continue  # same-author overlap -- not a cross-module conflict

        who = ", ".join(sorted({r.module_name for r in group}))
        message = (
            f'Multiple modules declare the same menu.xml `<add id="{menu_item_id}">`: {who} — '
            "Magento's admin menu builder throws a hard error on a duplicate id "
            "(\"Two 'add' commands cannot have equal id\"), not a silent override."
        )
        for module_id in module_ids:
            findings.append(
                (
                    module_id,
                    QualityFinding(
                        check_type="menu_item_id_conflict",
                        severity="warning",
                        file_path=None,
                        line=None,
                        message=message,
                    ),
                )
            )

    return findings
