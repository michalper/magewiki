from collections import defaultdict
from dataclasses import dataclass

from app.scanner.dto import QualityFinding


@dataclass
class CronJobRow:
    module_id: int
    module_name: str
    job_name: str
    instance_class: str
    method: str


def detect_cron_job_conflicts(jobs: list[CronJobRow]) -> list[tuple[int, QualityFinding]]:
    """Cross-module crontab.xml conflicts: two or more modules declaring a job
    with the same job code (the `name` attribute on `<job>`) but a different
    instance/method. Real impact, not theoretical — Magento merges every
    module's crontab.xml by job code into one final schedule, the same way it
    merges db_schema.xml by table/column name; a genuine disagreement means
    one module's job silently wins and the other module's own job never
    actually runs, which is easy to miss since the cron scheduler reports no
    error — it's just quietly running a different job under that code than
    the losing module expects.

    Same "flag a concrete, certain conflict" pragmatism as the rest of this
    family: two modules declaring the exact same job (identical instance and
    method — e.g. one module re-declaring a dependency's own job verbatim to
    adjust only its `<schedule>`, which Magento explicitly supports) is not
    flagged, only a genuine disagreement about which code actually runs.
    """
    groups: dict[str, list[CronJobRow]] = defaultdict(list)
    for j in jobs:
        groups[j.job_name].append(j)

    findings: list[tuple[int, QualityFinding]] = []

    for job_name, group in groups.items():
        module_ids = {j.module_id for j in group}
        if len(module_ids) < 2:
            continue  # same-author overlap -- not a cross-module conflict

        distinct_targets = {(j.instance_class, j.method) for j in group}
        if len(distinct_targets) < 2:
            continue  # every module points at the same instance/method -- not a conflict

        who = ", ".join(sorted({f"{j.module_name} -> {j.instance_class}::{j.method}" for j in group}))
        message = (
            f"Multiple modules declare a crontab.xml job with the same code `{job_name}`: {who} — "
            "Magento merges every module's crontab.xml by job code into one schedule; one module's "
            "job silently wins and the other's own job under this code never actually runs."
        )
        for module_id in module_ids:
            findings.append(
                (
                    module_id,
                    QualityFinding(
                        check_type="cron_job_conflict",
                        severity="warning",
                        file_path=None,
                        line=None,
                        message=message,
                    ),
                )
            )

    return findings
