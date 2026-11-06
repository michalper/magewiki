from pathlib import Path

import httpx

from app.config import settings
from app.scanner.dto import QualityFinding

_TOOL_CHECK_TYPES = {
    "phpstan": "phpstan_error",
    "phpmd": "phpmd_issue",
    "phpcs": "phpcs_violation",
    "rector": "php_compat_issue",
}


async def _call_tool(tool: str, module_path: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{settings.php_analyzer_url}/{tool}", json={"module_path": module_path})
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError:
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
    for tool, check_type in _TOOL_CHECK_TYPES.items():
        for item in await _call_tool(tool, str(module_root)):
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
