import subprocess

import httpx
import pytest

from app.ci import pr_gate


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_changed_files_runs_git_diff_and_splits_lines(monkeypatch):
    captured = {}

    def fake_run(cmd, cwd, check, capture_output, text):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(cmd, 0, stdout="a/File.php\nb/Other.php\n\n", stderr="")

    monkeypatch.setattr(pr_gate.subprocess, "run", fake_run)

    paths = pr_gate.changed_files("/repo", "origin/main")

    assert paths == ["a/File.php", "b/Other.php"]
    assert captured["cwd"] == "/repo"
    assert captured["cmd"] == ["git", "diff", "--name-only", "origin/main...HEAD"]


def test_fetch_findings_returns_empty_result_without_calling_the_api_when_there_are_no_paths(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("httpx.get should not be called with no changed paths")

    monkeypatch.setattr(pr_gate.httpx, "get", fail)

    result = pr_gate.fetch_findings("http://api", "/store", [])

    assert result.modules == []
    assert result.unmatched_paths == []
    assert result.has_blocking_finding is False


def test_fetch_findings_calls_the_endpoint_and_parses_modules_and_findings(monkeypatch):
    captured = {}

    def fake_get(url, params, timeout):
        captured["url"] = url
        captured["params"] = params
        return _FakeResponse(
            {
                "modules": [
                    {
                        "module_id": 1,
                        "name": "Vendor_Foo",
                        "path": "app/code/Vendor/Foo",
                        "matched_paths": ["app/code/Vendor/Foo/Model/Thing.php"],
                        "findings": [
                            {
                                "check_type": "hardcoded_secret",
                                "severity": "blocking",
                                "file_path": "Model/Thing.php",
                                "line": 12,
                                "message": "looks like an API key",
                            }
                        ],
                    }
                ],
                "unmatched_paths": ["README.md"],
            }
        )

    monkeypatch.setattr(pr_gate.httpx, "get", fake_get)

    result = pr_gate.fetch_findings(
        "http://api/", "/store", ["app/code/Vendor/Foo/Model/Thing.php", "README.md"]
    )

    assert captured["url"] == "http://api/modules/findings-by-path"
    assert captured["params"] == {
        "repo_root": "/store",
        "paths": "app/code/Vendor/Foo/Model/Thing.php,README.md",
    }
    assert result.unmatched_paths == ["README.md"]
    assert len(result.modules) == 1
    module = result.modules[0]
    assert module.name == "Vendor_Foo"
    assert module.findings[0].check_type == "hardcoded_secret"
    assert result.has_blocking_finding is True


def test_fetch_findings_raises_on_an_http_error(monkeypatch):
    def fake_get(url, params, timeout):
        raise httpx.HTTPStatusError("boom", request=httpx.Request("GET", url), response=httpx.Response(500))

    monkeypatch.setattr(pr_gate.httpx, "get", fake_get)

    with pytest.raises(httpx.HTTPStatusError):
        pr_gate.fetch_findings("http://api", "/store", ["a.php"])


def test_render_report_is_clean_when_there_are_no_findings_at_all():
    result = pr_gate.GateResult(modules=[], unmatched_paths=["README.md"])

    report = pr_gate.render_report(result)

    assert "✅ No blocking findings" in report
    assert "❌" not in report


def test_render_report_skips_a_matched_module_that_has_no_findings():
    clean_module = pr_gate.ModuleFindings(
        module_id=1, name="Vendor_Clean", path="app/code/Vendor/Clean", matched_paths=["x.php"], findings=[]
    )
    result = pr_gate.GateResult(modules=[clean_module], unmatched_paths=[])

    report = pr_gate.render_report(result)

    assert "Vendor_Clean" not in report
    assert "✅ No blocking findings" in report


def test_render_report_omits_the_line_number_from_the_citation_when_there_is_none():
    module = pr_gate.ModuleFindings(
        module_id=1,
        name="Vendor_Foo",
        path="app/code/Vendor/Foo",
        matched_paths=["composer.json"],
        findings=[
            pr_gate.Finding(
                check_type="composer_completeness",
                severity="warning",
                file_path="composer.json",
                line=None,
                message="missing require-dev",
            )
        ],
    )
    result = pr_gate.GateResult(modules=[module], unmatched_paths=[])

    report = pr_gate.render_report(result)

    assert "`composer.json`" in report
    assert "composer.json:None" not in report


def test_render_report_flags_blocking_findings_first_with_a_citation():
    module = pr_gate.ModuleFindings(
        module_id=1,
        name="Vendor_Foo",
        path="app/code/Vendor/Foo",
        matched_paths=["app/code/Vendor/Foo/Model/Thing.php"],
        findings=[
            pr_gate.Finding(
                check_type="phpstan_error", severity="warning", file_path=None, line=None, message="a warning"
            ),
            pr_gate.Finding(
                check_type="hardcoded_secret",
                severity="blocking",
                file_path="Model/Thing.php",
                line=12,
                message="looks like an API key",
            ),
        ],
    )
    result = pr_gate.GateResult(modules=[module], unmatched_paths=[])

    report = pr_gate.render_report(result)

    assert "❌ 1 blocking finding(s)" in report
    assert "### Vendor_Foo (`app/code/Vendor/Foo`)" in report
    blocking_line = next(line for line in report.splitlines() if "hardcoded_secret" in line)
    warning_line = next(line for line in report.splitlines() if "phpstan_error" in line)
    assert report.index(blocking_line) < report.index(warning_line)
    assert "`Model/Thing.php:12`" in blocking_line


def test_main_writes_the_report_and_returns_1_when_a_blocking_finding_is_touched(monkeypatch, tmp_path):
    monkeypatch.setattr(pr_gate, "changed_files", lambda local_checkout, base_ref: ["Model/Thing.php"])
    monkeypatch.setattr(
        pr_gate,
        "fetch_findings",
        lambda api_url, repo_root, paths: pr_gate.GateResult(
            modules=[
                pr_gate.ModuleFindings(
                    module_id=1,
                    name="Vendor_Foo",
                    path="app/code/Vendor/Foo",
                    matched_paths=paths,
                    findings=[
                        pr_gate.Finding(
                            check_type="hardcoded_secret",
                            severity="blocking",
                            file_path=None,
                            line=None,
                            message="m",
                        )
                    ],
                )
            ],
            unmatched_paths=[],
        ),
    )
    report_path = tmp_path / "report.md"

    exit_code = pr_gate.main(
        [
            "--local-checkout",
            str(tmp_path),
            "--base-ref",
            "origin/main",
            "--api-url",
            "http://api",
            "--magewiki-repo-root",
            "/store",
            "--report",
            str(report_path),
        ]
    )

    assert exit_code == 1
    assert "❌" in report_path.read_text()


def test_main_returns_0_when_nothing_blocking_is_touched(monkeypatch, tmp_path):
    monkeypatch.setattr(pr_gate, "changed_files", lambda local_checkout, base_ref: [])
    monkeypatch.setattr(
        pr_gate,
        "fetch_findings",
        lambda api_url, repo_root, paths: pr_gate.GateResult(modules=[], unmatched_paths=[]),
    )
    report_path = tmp_path / "report.md"

    exit_code = pr_gate.main(
        [
            "--local-checkout",
            str(tmp_path),
            "--base-ref",
            "origin/main",
            "--api-url",
            "http://api",
            "--magewiki-repo-root",
            "/store",
            "--report",
            str(report_path),
        ]
    )

    assert exit_code == 0
    assert "✅" in report_path.read_text()
