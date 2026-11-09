from collections import defaultdict
from dataclasses import dataclass

from app.scanner.dto import QualityFinding


@dataclass
class PreferenceRow:
    module_id: int
    module_name: str
    for_type: str
    preference_type: str


def detect_preference_conflicts(preferences: list[PreferenceRow]) -> list[tuple[int, QualityFinding]]:
    """Cross-module di.xml <preference> conflicts: two or more modules declaring
    a different implementation for the same interface. Real impact, not
    theoretical — Magento's DI compiler resolves each interface to exactly one
    preference, picked by module-sequence order; unlike a <plugin>'s explicit
    sortOrder or a documented override mechanism, a second module declaring its
    own preference for an interface someone else already owns has no
    deliberate layering intent behind it — one implementation silently wins
    and the other module's own preference is never actually used, which can
    be very hard to notice (the losing module keeps working as if its
    preference were active).

    Same "flag a concrete, certain conflict" pragmatism as
    plugin_conflicts.py/composer_conflicts.py/webapi_conflicts.py/
    db_schema_conflicts.py: only a genuine disagreement (different
    preference_type for the same for_type) is flagged, never a same-author
    restatement of the identical preference.
    """
    groups: dict[str, list[PreferenceRow]] = defaultdict(list)
    for p in preferences:
        groups[p.for_type].append(p)

    findings: list[tuple[int, QualityFinding]] = []

    for for_type, group in groups.items():
        module_ids = {p.module_id for p in group}
        if len(module_ids) < 2:
            continue  # same-author overlap -- not a cross-module conflict

        distinct_types = {p.preference_type for p in group}
        if len(distinct_types) < 2:
            continue  # every module agrees on the same implementation -- not a conflict

        who = ", ".join(sorted({f"{p.module_name} -> {p.preference_type}" for p in group}))
        message = (
            f"Multiple modules declare a di.xml `<preference for=\"{for_type}\">`: {who} — "
            "Magento resolves each interface to exactly one preference by module-sequence order; "
            "one module's implementation silently wins and the other's is never actually used."
        )
        for module_id in module_ids:
            findings.append(
                (
                    module_id,
                    QualityFinding(
                        check_type="preference_conflict",
                        severity="warning",
                        file_path=None,
                        line=None,
                        message=message,
                    ),
                )
            )

    return findings
