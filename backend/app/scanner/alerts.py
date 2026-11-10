import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass
class FindingIncrease:
    check_type: str
    previous_count: int
    current_count: int


@dataclass
class ModuleAlert:
    module_id: int
    module_name: str
    increases: list[FindingIncrease]


def compute_alert_increases(
    previous_counts: dict[str, int] | None,
    current_counts: dict[str, int],
    alertable_check_types: tuple[str, ...],
) -> list[FindingIncrease]:
    """`previous_counts` is None for a module's first-ever snapshot -- treated
    as all-zero, so a brand-new module whose very first scan already has a
    secret still alerts, rather than silently establishing a baseline that
    hides it. Only check_types in `alertable_check_types` are considered
    (secrets/CVEs by default, not routine PHPStan/PHPMD churn -- see
    app/config.py's ALERT_CHECK_TYPES), and only a genuine increase counts;
    a decrease (a finding got fixed) is never alert-worthy.
    """
    previous = previous_counts or {}
    increases = []
    for check_type in alertable_check_types:
        previous_count = previous.get(check_type, 0)
        current_count = current_counts.get(check_type, 0)
        if current_count > previous_count:
            increases.append(
                FindingIncrease(check_type=check_type, previous_count=previous_count, current_count=current_count)
            )
    return increases


def _format_text(repo_root: str, module_alerts: list[ModuleAlert]) -> str:
    lines = [f"MageWiki-AI: new quality findings in {repo_root}"]
    for alert in module_alerts:
        deltas = ", ".join(f"{i.check_type} {i.previous_count}→{i.current_count}" for i in alert.increases)
        lines.append(f"- {alert.module_name}: {deltas}")
    return "\n".join(lines)


async def send_quality_alert(webhook_url: str, repo_root: str, module_alerts: list[ModuleAlert]) -> None:
    """One POST per scan_repository run (not one per module) -- a repo with
    several new issues at once should read as one summary notification, not
    a burst, both to avoid spamming whatever `webhook_url` points at and
    because a controlled signal is the whole point (see CLAUDE.md's Phase 18
    decision). The top-level "text" field is deliberate: a bare Slack
    Incoming Webhook URL or a Google Chat webhook both render that field
    directly with zero adapter code, since both expect exactly {"text": ...}
    at minimum.

    Fails open on any HTTP error -- same convention as every other outgoing
    call in this codebase (e.g. app/scanner/magento_github.py): a flaky
    webhook endpoint must never fail the scan itself.
    """
    if not webhook_url or not module_alerts:
        return

    payload = {
        "event": "quality_alert",
        "repo_root": repo_root,
        "text": _format_text(repo_root, module_alerts),
        "modules": [
            {
                "module_id": alert.module_id,
                "module_name": alert.module_name,
                "increases": [
                    {
                        "check_type": i.check_type,
                        "previous_count": i.previous_count,
                        "current_count": i.current_count,
                    }
                    for i in alert.increases
                ],
            }
            for alert in module_alerts
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("quality-alert webhook POST to %r failed", webhook_url)
