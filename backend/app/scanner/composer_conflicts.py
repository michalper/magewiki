from collections import defaultdict
from dataclasses import dataclass

from app.scanner.dto import QualityFinding
from app.scanner.semver import constraints_overlap


@dataclass
class ComposerRequirementRow:
    module_id: int
    module_name: str
    package_name: str
    constraint: str


def detect_composer_conflicts(requirements: list[ComposerRequirementRow]) -> list[tuple[int, QualityFinding]]:
    """Cross-module Composer version-constraint conflicts: two or more modules
    requiring the same package with ranges that don't overlap at all. Real
    impact, not theoretical — `composer install` resolves exactly one version
    of a package for the whole project, shared by every module that requires
    it; if no single version satisfies every requirer, the install fails for
    the entire store, not just the conflicting modules. Deliberately checked
    pairwise (not full N-way intersection across every requirer of a
    package) — the same pragmatic, "flag a concrete incompatible pair, don't
    solve full SAT" approach `plugin_conflicts.py` already takes, and the
    common real case (two modules, two incompatible ranges) is exactly a pair.

    Magento's own packages (magento/framework, magento/module-*) are
    deliberately NOT excluded here, unlike the CVE check -- that check
    excludes them because Magento's packages aren't resolvable via public
    Packagist, but this check never calls Packagist at all, just compares
    constraint strings, and a magento/module-* version mismatch between two
    extensions is one of the most common real version conflicts in practice.
    """
    by_package: dict[str, list[ComposerRequirementRow]] = defaultdict(list)
    for r in requirements:
        by_package[r.package_name].append(r)

    findings: list[tuple[int, QualityFinding]] = []

    for package_name, reqs in by_package.items():
        if len({r.module_id for r in reqs}) < 2:
            continue  # same-author overlap -- not a cross-module conflict

        conflicting_modules: set[int] = set()
        conflicting_pairs: list[tuple[ComposerRequirementRow, ComposerRequirementRow]] = []
        for i, a in enumerate(reqs):
            for b in reqs[i + 1 :]:
                if a.module_id == b.module_id:
                    continue
                if not constraints_overlap(a.constraint, b.constraint):
                    conflicting_modules.update({a.module_id, b.module_id})
                    conflicting_pairs.append((a, b))

        if not conflicting_pairs:
            continue

        who = ", ".join(
            sorted({f"{r.module_name} requires {r.constraint}" for pair in conflicting_pairs for r in pair})
        )
        message = (
            f"Conflicting composer version requirements for {package_name}: {who} — composer install "
            "resolves exactly one version of a package for the whole store, and these ranges don't overlap."
        )
        for module_id in conflicting_modules:
            findings.append(
                (
                    module_id,
                    QualityFinding(check_type="composer_conflict", severity="warning", file_path=None, line=None, message=message),
                )
            )

    return findings
