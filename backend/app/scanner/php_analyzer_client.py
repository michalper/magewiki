import logging
from pathlib import Path

import httpx

from app.config import settings
from app.scanner.dto import QualityFinding

logger = logging.getLogger(__name__)

_TOOL_CHECK_TYPES = {
    "phpstan": "phpstan_error",
    "phpmd": "phpmd_issue",
    "phpcs": "phpcs_violation",
    "rector": "php_compat_issue",
}


async def _call_tool(tool: str, module_path: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{settings.php_analyzer_url}/{tool}", json={"module_path": module_path})
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError:
        logger.warning("php-analyzer %s call failed for %s", tool, module_path, exc_info=True)
        return []
    except ValueError:
        # PHP's built-in dev server returns 200 with an empty body on an
        # uncaught exception/fatal error inside index.php, rather than a
        # proper 500 — raise_for_status() doesn't catch that (200 isn't an
        # error status), so response.json() raises json.JSONDecodeError
        # (a ValueError subclass) on the empty body instead. Confirmed in
        # production: this previously propagated all the way up and failed
        # the *whole module's* persistence, not just "no findings from this
        # tool" as the fail-open contract here promises.
        logger.warning("php-analyzer %s returned an unparseable response for %s", tool, module_path)
        return []
    if not isinstance(data, dict):
        return []
    return data.get("findings", [])


def _relativize(file_path: str, module_root: Path) -> str:
    try:
        return str(Path(file_path).relative_to(module_root))
    except ValueError:
        return file_path


async def check_php_static_analysis(module_root: Path) -> list[QualityFinding]:
    """Real PHP static analysis via the php-analyzer sidecar (Phase 12) — the
    one case where MageWiki shells out to real PHP tooling rather than just
    parsing with tree-sitter. Fails open per tool (a sidecar outage degrades
    to "no findings from that tool", never a scan failure); all four check
    types default to "warning" — informational, not blocking, since there's
    no "upgrade readiness" gate concept yet to make php_compat_issue
    meaningful as a hard blocker the way v1 treats it.
    """
    findings: list[QualityFinding] = []
    tools = list(_TOOL_CHECK_TYPES.items())
    # Sequential, not concurrent: the sidecar's PHP built-in dev server
    # (`php -S`) is single-threaded, so four concurrent calls queue up
    # server-side regardless — confirmed in production, this cost nothing in
    # real wall-clock time (the server processes them one at a time either
    # way) but silently lost findings from whichever tool landed last in the
    # queue, since every call's client-side timeout clock started ticking at
    # dispatch time, not at its actual turn to run, and a large real module
    # (828 classes) pushed the last tool's wait-plus-processing time past the
    # old 60s timeout with nothing logged. Calling sequentially gives each
    # tool a fresh timeout window starting when it actually begins running.
    results = [await _call_tool(tool, str(module_root)) for tool, _check_type in tools]
    for (_tool, check_type), items in zip(tools, results, strict=True):
        for item in items:
            findings.append(
                QualityFinding(
                    check_type=check_type,
                    severity="warning",
                    file_path=_relativize(item.get("file", ""), module_root) if item.get("file") else None,
                    line=item.get("line"),
                    message=item.get("message", ""),
                )
            )
    return findings
