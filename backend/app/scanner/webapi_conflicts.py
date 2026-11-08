from collections import defaultdict
from dataclasses import dataclass

from app.scanner.dto import QualityFinding


@dataclass
class WebapiRouteRow:
    module_id: int
    module_name: str
    url: str
    http_method: str
    service_class: str
    service_method: str


def detect_webapi_route_conflicts(routes: list[WebapiRouteRow]) -> list[tuple[int, QualityFinding]]:
    """Cross-module REST route conflicts: two or more modules declaring the
    exact same (url, http_method) pair in their own webapi.xml. Real impact,
    not theoretical: Magento merges every installed module's route
    declarations into one table keyed by (url, method) at compile time — an
    exact duplicate is genuinely ambiguous, with one module's service
    silently winning over the other depending on compilation order, not a
    documented, deterministic resolution the way a webapi.xml <route>
    override normally works.

    Matched on the literal url string only, not on path-parameter shape
    (e.g. "/V1/foo/:id" vs "/V1/foo/:bar" are treated as different routes
    even though both would match the same real request) -- deliberately
    conservative, same "flag a concrete, certain conflict" pragmatism as
    plugin_conflicts.py/composer_conflicts.py, to avoid a false positive on
    two genuinely distinct, non-colliding routes.
    """
    groups: dict[tuple[str, str], list[WebapiRouteRow]] = defaultdict(list)
    for r in routes:
        groups[(r.url, r.http_method.upper())].append(r)

    findings: list[tuple[int, QualityFinding]] = []

    for (url, http_method), group in groups.items():
        module_ids = {r.module_id for r in group}
        if len(module_ids) < 2:
            continue  # same-author overlap -- not a cross-module conflict

        who = ", ".join(sorted({f"{r.module_name} -> {r.service_class}::{r.service_method}" for r in group}))
        message = (
            f"Multiple modules declare the same webapi.xml route `{http_method} {url}`: {who} — "
            "Magento merges every module's route table by (url, method); an exact duplicate is "
            "ambiguous, with one module's service silently winning depending on compilation order."
        )
        for module_id in module_ids:
            findings.append(
                (
                    module_id,
                    QualityFinding(
                        check_type="webapi_route_conflict",
                        severity="warning",
                        file_path=None,
                        line=None,
                        message=message,
                    ),
                )
            )

    return findings
