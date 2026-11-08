import logging
from pathlib import Path

import httpx

from app.config import settings
from app.scanner.dto import QualityFinding, TestExecutionResult
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
                class_name = item.get("class", "")
                # A trailing "\\" means PhpMetrics reported a namespace
                # *prefix* (a package-level rule like Stable Dependencies
                # Principle), never a real FQCN — resolve straight to "no
                # file" rather than doing the lookup, since a real FQCN can
                # legitimately equal that same string with the trailing
                # backslash stripped (e.g. a class literally named
                # "Vendor\Module"), which would otherwise be mis-attributed
                # a package-level finding that isn't really about it.
                resolved_file = None if class_name.endswith("\\") else (fqcn_to_file or {}).get(class_name)
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


async def check_php_unit_tests(
    module_root: Path, php_constraint: str | None = None
) -> tuple[TestExecutionResult, list[QualityFinding]]:
    """Actually run a module's own Test/Unit/ suite via its own
    vendor/bin/phpunit -- the first check in this file that executes scanned
    code rather than only parsing/analysing it statically, so it's scoped
    deliberately narrower than every other check here:

    - Unit tests only, never Integration/ -- those need a real bootstrapped
      Magento install with a real database, which this sidecar deliberately
      doesn't have (same boundary check_php_static_analysis already draws
      around a real vendor/magento/framework).
    - Only the MODULE's own vendor/bin/phpunit and its own
      phpunit.xml/phpunit.xml.dist, never a containing store's dev/tests/unit
      harness -- confirmed empirically against a real module
      (Ordo_Automation) nested inside a full Magento checkout that the other
      way genuinely doesn't work: the module's own Test/Unit/bootstrap.php
      resolves its own "../../vendor/autoload.php" relative to the module's
      own root, which only exists when that module was composer-installed
      standalone, not when nested three levels deep inside a store's vendor/
      tree. A module relying only on a containing store's test harness
      simply doesn't get this check -- not a regression, the same kind of
      scope limit Test/Integration/Test/Api already have. No real phpunit +
      own config means nothing to run -- not a failure, just
      TestExecutionResult(executed=False).

    Real sandboxing, not just "it's in a container": see php-analyzer's
    run_phpunit() for the actual hardening (wall-clock timeout,
    disable_functions blocking shell/process-spawning functions, a capped
    memory_limit) -- this is the one call in this whole scanner that
    genuinely executes third-party PHP code, which is a different risk class
    than everything else here. Verified directly against a real module
    (Ordo_Automation, 3013 real tests): disable_functions doesn't break a
    real test suite, and a wall-clock timeout genuinely SIGKILLs a hung
    process rather than just politely asking it to stop.
    """
    payload: dict[str, str] = {
        "module_path": str(module_root),
        "php_binary": _pick_php_binary(php_constraint),
    }
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(f"{settings.php_analyzer_url}/phpunit", json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError:
        logger.warning("php-analyzer phpunit call failed for %s", module_root, exc_info=True)
        return TestExecutionResult(executed=False), []
    except ValueError:
        logger.warning("php-analyzer phpunit returned an unparseable response for %s", module_root)
        return TestExecutionResult(executed=False), []

    if not isinstance(data, dict) or not data.get("executed"):
        return TestExecutionResult(executed=False), []

    result = TestExecutionResult(
        executed=True,
        tests_run=int(data.get("tests_run") or 0),
        tests_failed=int(data.get("tests_failed") or 0),
        coverage_percent=data.get("coverage_percent"),
    )
    findings = [
        QualityFinding(
            check_type="phpunit_failure",
            severity="warning",
            file_path=None,
            line=None,
            message=f"{failure.get('test', 'unknown test')}: {failure.get('message', '')}".strip(": "),
        )
        for failure in data.get("failures", [])
        if isinstance(failure, dict)
    ]
    return result, findings
