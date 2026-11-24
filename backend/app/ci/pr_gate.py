"""MageWiki PR gate (Phase 26) -- a standalone CLI, not part of the FastAPI
backend process. It runs inside a *third-party* Magento store's own CI job
and fails that job's check when the pull request touches a module that a
MageWiki instance already knows has a blocking quality finding (CVE,
hardcoded secret, Magento-upgrade blocker, ...). Deliberately dependency-light
-- stdlib + httpx only, no `app.models`/`app.db`/FastAPI/SQLAlchemy imports --
so the consumer repo's CI image only needs `pip install httpx`, not the whole
backend. See CLAUDE.md's Phase 26 entry and docs/roadmap.md for the design.

Reads the *already-scanned* state of the target repo (whatever commit the
nightly cron / webhook last scanned) -- it does not trigger a fresh scan of
the PR branch itself.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

_SEVERITY_BADGE = {"blocking": "\U0001f534", "warning": "\U0001f7e0", "info": "\U0001f535"}


@dataclass
class Finding:
    check_type: str
    severity: str
    file_path: str | None
    line: int | None
    message: str


@dataclass
class ModuleFindings:
    module_id: int
    name: str
    path: str
    matched_paths: list[str]
    findings: list[Finding]


@dataclass
class GateResult:
    modules: list[ModuleFindings]
    unmatched_paths: list[str]

    @property
    def has_blocking_finding(self) -> bool:
        return any(finding.severity == "blocking" for module in self.modules for finding in module.findings)


def changed_files(local_checkout: str, base_ref: str) -> list[str]:
    """Every file this PR's branch (HEAD, checked out at `local_checkout`)
    changes relative to `base_ref` -- plain `git diff`, no MageWiki call.
    """
    output = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        cwd=local_checkout,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line.strip() for line in output.splitlines() if line.strip()]


def fetch_findings(api_url: str, magewiki_repo_root: str, paths: list[str]) -> GateResult:
    """Resolves `paths` against a running MageWiki instance's
    GET /modules/findings-by-path. `magewiki_repo_root` is the `repo_root`
    value MageWiki's own scanner stored for this store -- deliberately not
    `local_checkout` (the CI job's ephemeral checkout path, e.g.
    /home/runner/work/..., never matches whatever path the nightly scanner
    used).
    """
    if not paths:
        return GateResult(modules=[], unmatched_paths=[])

    response = httpx.get(
        f"{api_url.rstrip('/')}/modules/findings-by-path",
        params={"repo_root": magewiki_repo_root, "paths": ",".join(paths)},
        timeout=30.0,
    )
    response.raise_for_status()
    body = response.json()

    modules = [
        ModuleFindings(
            module_id=module["module_id"],
            name=module["name"],
            path=module["path"],
            matched_paths=module["matched_paths"],
            findings=[Finding(**finding) for finding in module["findings"]],
        )
        for module in body["modules"]
    ]
    return GateResult(modules=modules, unmatched_paths=body["unmatched_paths"])


def render_report(result: GateResult) -> str:
    """The sticky PR-comment body (same marocchino/sticky-pull-request-
    comment pattern the Phase 7b RAG-eval comment already uses). Blocking
    findings first, so the verdict is readable without scrolling.
    """
    blocking_count = sum(
        1 for module in result.modules for finding in module.findings if finding.severity == "blocking"
    )
    lines = ["## MageWiki PR gate", ""]
    if blocking_count:
        lines.append(f"❌ {blocking_count} blocking finding(s) on modules this PR touches — merge blocked.")
    else:
        lines.append("✅ No blocking findings on the modules this PR touches.")
    lines.append("")

    for module in sorted(result.modules, key=lambda m: m.name):
        if not module.findings:
            continue
        lines.append(f"### {module.name} (`{module.path}`)")
        for finding in sorted(module.findings, key=lambda f: (f.severity != "blocking", f.check_type)):
            badge = _SEVERITY_BADGE.get(finding.severity, "⚪")
            citation = ""
            if finding.file_path:
                location = f"{finding.file_path}:{finding.line}" if finding.line is not None else finding.file_path
                citation = f" — `{location}`"
            lines.append(f"- {badge} **{finding.check_type}**: {finding.message}{citation}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MageWiki PR gate")
    parser.add_argument("--local-checkout", required=True, help="git checkout to diff (for git diff only)")
    parser.add_argument("--base-ref", required=True, help="e.g. origin/main -- diffed against HEAD")
    parser.add_argument("--api-url", required=True, help="base URL of a reachable MageWiki instance")
    parser.add_argument(
        "--magewiki-repo-root", required=True, help="the repo_root value stored in MageWiki's DB for this store"
    )
    parser.add_argument("--report", required=True, help="Markdown report output path")
    args = parser.parse_args(argv)

    paths = changed_files(args.local_checkout, args.base_ref)
    result = fetch_findings(args.api_url, args.magewiki_repo_root, paths)
    report = render_report(result)

    with Path(args.report).open("w") as report_file:
        report_file.write(report)
    print(report)

    return 1 if result.has_blocking_finding else 0


if __name__ == "__main__":  # pragma: no cover - entry-point guard, exercised via subprocess, not instrumented
    sys.exit(main())
