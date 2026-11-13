from collections import defaultdict
from dataclasses import dataclass

from app.scanner.dto import QualityFinding


@dataclass
class VirtualTypeRow:
    module_id: int
    module_name: str
    name: str
    virtual_type: str


def detect_virtual_type_conflicts(virtual_types: list[VirtualTypeRow]) -> list[tuple[int, QualityFinding]]:
    """Cross-module di.xml <virtualType> conflicts: two or more modules declaring
    the same virtualType `name` with a *different* backing `type`. Same shape as
    preference_conflicts.py's own reasoning, not indexer_conflicts.py's plain
    duplicate-id shape: a virtualType name is deliberately reused by its own
    author across several of their own di.xml declarations (composing the same
    virtual class from multiple angles), so only a genuine disagreement -- a
    different module supplying a different backing type for the identical name
    -- is a real conflict. Magento's DI compiler resolves a virtualType name to
    exactly one backing type; a second, disagreeing declaration has one silently
    win and the other module's own declaration is never actually used.
    """
    groups: dict[str, list[VirtualTypeRow]] = defaultdict(list)
    for v in virtual_types:
        groups[v.name].append(v)

    findings: list[tuple[int, QualityFinding]] = []

    for name, group in groups.items():
        module_ids = {v.module_id for v in group}
        if len(module_ids) < 2:
            continue  # same-author overlap -- not a cross-module conflict

        distinct_types = {v.virtual_type for v in group}
        if len(distinct_types) < 2:
            continue  # every module agrees on the same backing type -- not a conflict

        who = ", ".join(sorted({f"{v.module_name} -> {v.virtual_type}" for v in group}))
        message = (
            f'Multiple modules declare a di.xml `<virtualType name="{name}">` with a different backing '
            f"type: {who} — Magento resolves each virtualType name to exactly one backing type by "
            "module-sequence order; one module's declaration silently wins and the other's is never "
            "actually used."
        )
        for module_id in module_ids:
            findings.append(
                (
                    module_id,
                    QualityFinding(
                        check_type="virtual_type_conflict",
                        severity="warning",
                        file_path=None,
                        line=None,
                        message=message,
                    ),
                )
            )

    return findings
