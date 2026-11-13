from collections import defaultdict
from dataclasses import dataclass

from app.scanner.dto import QualityFinding


@dataclass
class CacheTypeRow:
    module_id: int
    module_name: str
    cache_type_id: str
    instance: str | None


def detect_cache_type_conflicts(cache_types: list[CacheTypeRow]) -> list[tuple[int, QualityFinding]]:
    """Cross-module cache.xml conflicts: two or more modules declaring a
    `<type>` with the same name but a different `instance`. Unlike
    menu.xml/widget.xml, a same-name re-declaration of a cache type is a
    real, intentional pattern (a module legitimately overriding a core
    cache type's cosmetic attributes, e.g. `<label>`, without touching its
    backing class) -- only a genuine disagreement on `instance` is flagged,
    same "different value for the same key" shape as preference_conflict.
    A module that re-declares the name without setting `instance` at all
    (None) is never itself a disagreement -- only distinct, non-null
    instance values across 2+ modules count.
    """
    groups: dict[str, list[CacheTypeRow]] = defaultdict(list)
    for r in cache_types:
        groups[r.cache_type_id].append(r)

    findings: list[tuple[int, QualityFinding]] = []

    for cache_type_id, group in groups.items():
        module_ids = {r.module_id for r in group}
        if len(module_ids) < 2:
            continue  # same-author overlap -- not a cross-module conflict

        distinct_instances = {r.instance for r in group if r.instance is not None}
        if len(distinct_instances) < 2:
            continue  # no real disagreement on the backing implementation

        who = ", ".join(
            sorted({f"{r.module_name} -> {r.instance}" for r in group if r.instance is not None})
        )
        message = (
            f'Multiple modules declare the same cache.xml `<type name="{cache_type_id}">` '
            f"with a different instance: {who} — Magento's config merge resolves this by "
            "module-sequence order; one module's backing class silently wins."
        )
        for module_id in module_ids:
            findings.append(
                (
                    module_id,
                    QualityFinding(
                        check_type="cache_type_conflict",
                        severity="warning",
                        file_path=None,
                        line=None,
                        message=message,
                    ),
                )
            )

    return findings
