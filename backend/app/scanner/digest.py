import logging

import httpx

from app.search.fleet_digest import FleetDigest

logger = logging.getLogger(__name__)


def _format_text(digest: FleetDigest) -> str:
    if not digest.new_modules and not digest.changed_modules:
        return "MageWiki-AI weekly fleet digest: no changes in the fleet this week."

    lines = ["MageWiki-AI weekly fleet digest:"]
    lines.extend(f"- {module_name}: newly scanned" for _module_id, module_name in digest.new_modules)
    lines.extend(
        f"- {change.module_name}: {change.previous_total}→{change.current_total} findings"
        for change in digest.changed_modules
    )
    lines.append(f"Fleet-wide finding delta: {digest.total_delta:+d}")
    return "\n".join(lines)


async def send_fleet_digest(webhook_url: str, digest: FleetDigest) -> None:
    """Weekly heartbeat POST, not a threshold-crossing alert (contrast with
    app/scanner/alerts.py::send_quality_alert): fires every week on schedule
    *including* a quiet week, since the point is a regular status report,
    not just bad news. Only `webhook_url` being empty skips the POST.

    Same "text" field and fail-open convention as send_quality_alert, for
    the same reasons (zero-adapter Slack/Google Chat compatibility; a flaky
    webhook endpoint must never fail the cron job itself).
    """
    if not webhook_url:
        return

    payload = {
        "event": "fleet_digest",
        "window_start": digest.window_start.isoformat(),
        "text": _format_text(digest),
        "new_modules": [
            {"module_id": module_id, "module_name": module_name} for module_id, module_name in digest.new_modules
        ],
        "changed_modules": [
            {
                "module_id": change.module_id,
                "module_name": change.module_name,
                "previous_total": change.previous_total,
                "current_total": change.current_total,
            }
            for change in digest.changed_modules
        ],
        "total_delta": digest.total_delta,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()
    except httpx.HTTPError:
        logger.exception("fleet-digest webhook POST to %r failed", webhook_url)
