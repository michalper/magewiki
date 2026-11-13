from collections import defaultdict
from dataclasses import dataclass

from app.scanner.dto import QualityFinding


@dataclass
class RouteRow:
    module_id: int
    module_name: str
    area: str
    route_id: str
    front_name: str


def detect_route_id_conflicts(routes: list[RouteRow]) -> list[tuple[int, QualityFinding]]:
    """Cross-module routes.xml conflicts: two or more modules declaring a
    <route> with the exact same id *in the same area* (frontend or
    adminhtml -- Magento's own uniqueness constraint is per-area, so the
    same id reused across areas is not a conflict). Real impact, not
    theoretical: a route id is also how `getUrl('route_id/...')` resolves a
    URL by reverse lookup, so a duplicate id makes that resolution
    ambiguous, same risk class as a duplicate acl.xml resource id or
    indexer.xml id. The (area, id) pair is the whole conflict signal;
    same-author restatement of the identical pair is not flagged.
    """
    groups: dict[tuple[str, str], list[RouteRow]] = defaultdict(list)
    for r in routes:
        groups[(r.area, r.route_id)].append(r)

    findings: list[tuple[int, QualityFinding]] = []

    for (area, route_id), group in groups.items():
        module_ids = {r.module_id for r in group}
        if len(module_ids) < 2:
            continue  # same-author overlap -- not a cross-module conflict

        who = ", ".join(sorted({r.module_name for r in group}))
        message = (
            f'Multiple modules declare the same {area} routes.xml `<route id="{route_id}">`: {who} — '
            "Magento merges every module's route table by (area, id); an exact duplicate is ambiguous, "
            "with reverse-URL generation (getUrl) silently resolving to whichever module's "
            "declaration wins depending on compilation order."
        )
        for module_id in module_ids:
            findings.append(
                (
                    module_id,
                    QualityFinding(
                        check_type="route_id_conflict",
                        severity="warning",
                        file_path=None,
                        line=None,
                        message=message,
                    ),
                )
            )

    return findings


def detect_frontname_conflicts(routes: list[RouteRow]) -> list[tuple[int, QualityFinding]]:
    """Cross-module routes.xml conflicts: two or more modules declaring a
    <route> with the exact same frontName *in the same area* -- the
    frontName is the literal URL segment Magento's router dispatches on
    (e.g. admin/<frontName>/...), so a duplicate frontName is a genuine URL
    dispatch ambiguity, distinct from (and more commonly cited than) a
    duplicate route id: two modules can share a route id with different
    frontNames (or vice versa) without either symptom necessarily implying
    the other, so this is tracked as its own check_type rather than folded
    into route_id_conflict.
    """
    groups: dict[tuple[str, str], list[RouteRow]] = defaultdict(list)
    for r in routes:
        groups[(r.area, r.front_name)].append(r)

    findings: list[tuple[int, QualityFinding]] = []

    for (area, front_name), group in groups.items():
        module_ids = {r.module_id for r in group}
        if len(module_ids) < 2:
            continue  # same-author overlap -- not a cross-module conflict

        who = ", ".join(sorted({r.module_name for r in group}))
        message = (
            f'Multiple modules declare the same {area} routes.xml frontName "{front_name}": {who} — '
            "Magento dispatches URLs by (area, frontName); an exact duplicate is ambiguous, "
            "with one module's controllers silently winning depending on compilation order."
        )
        for module_id in module_ids:
            findings.append(
                (
                    module_id,
                    QualityFinding(
                        check_type="frontname_conflict",
                        severity="warning",
                        file_path=None,
                        line=None,
                        message=message,
                    ),
                )
            )

    return findings
