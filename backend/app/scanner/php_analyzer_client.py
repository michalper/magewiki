import logging
from pathlib import Path

import httpx

from app.config import settings
from app.scanner.dto import QualityFinding
from app.scanner.semver import constraints_overlap

logger = logging.getLogger(__name__)

# PHP versions actually installed side by side in the php-analyzer sidecar
# (see php-analyzer/Dockerfile) — highest first, so the loop below prefers
# the newest version a module's own composer.json php constraint allows.
# Composer's own platform_check.php enforces a scanned module's declared PHP
# version strictly when its real vendor/autoload.php is used for bitexpert/
# phpstan-magento's class resolution (see CLAUDE.md's decision note) — a
# single fixed interpreter version can never satisfy every scanned module.
_AVAILABLE_PHP_BINARIES = [("php85", 5), ("php84", 4), ("php83", 3)]
_DEFAULT_PHP_BINARY = "php84"


def _pick_php_binary(php_constraint: str | None) -> str:
    if not php_constraint:
        return _DEFAULT_PHP_BINARY
    for binary, minor in _AVAILABLE_PHP_BINARIES:
        if constraints_overlap(php_constraint, f">=8.{minor}.0 <8.{minor + 1}.0"):
            return binary
    return _DEFAULT_PHP_BINARY

_TOOL_CHECK_TYPES = {
    "phpstan": "phpstan_error",
    "phpmd": "phpmd_issue",
    "phpcs": "phpcs_violation",
    "rector": "php_compat_issue",
    "phpmetrics": "phpmetrics_issue",
}

# phpmetrics is the one tool here whose findings key by class FQCN (or, for a
# package-level rule, a namespace prefix) rather than a real file path --
# di.xml and the other three tools never need this, since they already
# report an actual file. Resolved against this module's own already-
# cataloged PhpClass rows (fqcn -> relative file_path); a namespace prefix
# never matches a real FQCN, so a package-level finding naturally resolves
# to no file, which is correct -- there isn't one.
_CLASS_KEYED_TOOLS = {"phpmetrics"}


async def _call_tool(tool: str, module_path: str, magento_root: str | None, php_binary: str) -> list[dict]:
    payload: dict[str, str] = {"module_path": module_path, "php_binary": php_binary}
    if magento_root is not None:
        payload["magento_root"] = magento_root
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{settings.php_analyzer_url}/{tool}", json=payload)
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


async def check_php_static_analysis(
    module_root: Path, repo_root: Path, php_constraint: str | None = None, fqcn_to_file: dict[str, str] | None = None
) -> list[QualityFinding]:
    """Real PHP static analysis via the php-analyzer sidecar (Phase 12) — the
    one case where MageWiki shells out to real PHP tooling rather than just
    parsing with tree-sitter. Fails open per tool (a sidecar outage degrades
    to "no findings from that tool", never a scan failure); every check type
    defaults to "warning" — informational, not blocking, since there's no
    "upgrade readiness" gate concept yet to make php_compat_issue meaningful
    as a hard blocker the way v1 treats it.

    fqcn_to_file resolves phpmetrics' class/package-keyed findings to this
    module's own already-cataloged file paths (see _CLASS_KEYED_TOOLS) —
    every other tool here reports a real file path directly and never needs
    this.

    repo_root (the scanned store's root, not just this one module) is passed
    to phpstan only, as bitexpert/phpstan-magento's magentoRoot — a module
    nested inside a real store (e.g. vendor/amasty/base) needs the *store's*
    vendor/magento/framework, not its own; repo_root already equals
    module_root for a standalone, self-contained checkout (confirmed against
    the real Ordo_Automation fixture, which ships its own full vendor/magento/*
    and is scanned standalone).

    php_constraint (the module's own composer.json php requirement) picks
    which of the sidecar's side-by-side PHP interpreters (8.3/8.4/8.5 — see
    php-analyzer/Dockerfile) runs every tool for this module: Composer's own
    platform_check.php enforces a scanned module's declared PHP version
    strictly once its real vendor/autoload.php is loaded for bitexpert/
    phpstan-magento's class resolution, and no single fixed interpreter
    version can satisfy every scanned module's own requirement.
    """
    findings: list[QualityFinding] = []
    tools = list(_TOOL_CHECK_TYPES.items())
    php_binary = _pick_php_binary(php_constraint)
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
    results = [
        await _call_tool(tool, str(module_root), str(repo_root) if tool == "phpstan" else None, php_binary)
        for tool, _check_type in tools
    ]
    for (tool, check_type), items in zip(tools, results, strict=True):
        for item in items:
            if tool in _CLASS_KEYED_TOOLS:
                resolved_file = (fqcn_to_file or {}).get(item.get("class", ""))
            else:
                resolved_file = item.get("file") or None

            # Every tool is asked to exclude Test/ at its own CLI level too
            # (cheaper — it skips analysing those files at all), but phpmd's
            # own --exclude pattern matching proved unreliable combining
            # multiple patterns (confirmed directly: a combined pattern
            # silently excluded everything, not just Test/) — this is the one
            # place the policy is guaranteed correct regardless of any one
            # tool's own exclude-flag quirks. PHPUnit mock/stub code is a
            # different quality concern than the production code these
            # checks are meant to flag. Checked by path *segment*, not
            # substring, since phpstan/phpmd/phpcs/rector report an absolute
            # path ("/.../Test/Unit/Foo.php") while phpmetrics' class-keyed
            # findings resolve to this module's own already-relative
            # PhpClassEntry.file_path ("Test/Unit/Foo.php", no leading "/") —
            # a plain "/Test/" substring check would miss the latter shape.
            if resolved_file and "Test" in Path(resolved_file).parts:
                continue
            findings.append(
                QualityFinding(
                    check_type=check_type,
                    severity="warning",
                    file_path=_relativize(resolved_file, module_root) if resolved_file else None,
                    line=item.get("line"),
                    message=item.get("message", ""),
                )
            )
    return findings
