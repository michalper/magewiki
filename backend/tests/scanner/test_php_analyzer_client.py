from pathlib import Path

import httpx
import pytest

from app.scanner.php_analyzer_client import check_php_static_analysis


class _FakeResponse:
    def __init__(self, json_data: dict):
        self._json = json_data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._json


class _FakeAsyncClient:
    def __init__(self, findings_by_tool: dict[str, list[dict]], *args, **kwargs):
        self._findings_by_tool = findings_by_tool
        self.calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None):
        tool = url.rsplit("/", 1)[-1]
        self.calls.append(tool)
        return _FakeResponse({"findings": self._findings_by_tool.get(tool, [])})


class _RaisingAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None):
        raise httpx.ConnectError("connection refused")


class _EmptyBodyResponse:
    """PHP's built-in dev server returns 200 with an empty body on an
    uncaught exception/fatal error inside index.php, rather than a proper
    500 — confirmed in production. raise_for_status() doesn't catch that
    (200 isn't an error status), so .json() then raises json.JSONDecodeError
    on the empty body, same as this fake.
    """

    status_code = 200

    def raise_for_status(self) -> None:
        pass

    def json(self):
        import json

        return json.loads("")


class _EmptyBodyAsyncClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None):
        return _EmptyBodyResponse()


@pytest.mark.asyncio
async def test_check_php_static_analysis_maps_each_tool_to_its_check_type(tmp_path, monkeypatch):
    module_root = tmp_path / "Vendor" / "Module"
    module_root.mkdir(parents=True)
    findings_by_tool = {
        "phpstan": [{"file": str(module_root / "Foo.php"), "line": 10, "message": "Unknown class."}],
        "phpmd": [{"file": str(module_root / "Bar.php"), "line": 5, "message": "Too complex."}],
        "phpcs": [{"file": str(module_root / "Baz.php"), "line": 3, "message": "Magento2.Sniff: bad."}],
        "rector": [{"file": str(module_root / "Qux.php"), "line": None, "message": "Rector would apply: X"}],
    }
    monkeypatch.setattr(
        "app.scanner.php_analyzer_client.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient(findings_by_tool)
    )

    findings = await check_php_static_analysis(module_root, module_root)

    by_check_type = {f.check_type: f for f in findings}
    assert set(by_check_type) == {"phpstan_error", "phpmd_issue", "phpcs_violation", "php_compat_issue"}
    assert by_check_type["phpstan_error"].file_path == "Foo.php"
    assert by_check_type["phpstan_error"].severity == "warning"
    assert by_check_type["phpcs_violation"].message == "Magento2.Sniff: bad."


@pytest.mark.asyncio
async def test_check_php_static_analysis_fails_open_on_connection_error(tmp_path, monkeypatch):
    module_root = tmp_path / "Vendor" / "Module"
    module_root.mkdir(parents=True)
    monkeypatch.setattr("app.scanner.php_analyzer_client.httpx.AsyncClient", lambda *a, **k: _RaisingAsyncClient())

    findings = await check_php_static_analysis(module_root, module_root)

    assert findings == []


@pytest.mark.asyncio
async def test_check_php_static_analysis_fails_open_on_an_empty_200_body(tmp_path, monkeypatch):
    """Regression test: this previously propagated a bare json.JSONDecodeError
    all the way up through check_php_static_analysis, failing persistence of
    the *whole module* in scan_repository — not just "no findings from this
    one tool", which is what every other failure mode here is designed to
    degrade to.
    """
    module_root = tmp_path / "Vendor" / "Module"
    module_root.mkdir(parents=True)
    monkeypatch.setattr(
        "app.scanner.php_analyzer_client.httpx.AsyncClient", lambda *a, **k: _EmptyBodyAsyncClient()
    )

    findings = await check_php_static_analysis(module_root, module_root)

    assert findings == []


@pytest.mark.asyncio
async def test_check_php_static_analysis_with_no_findings(tmp_path, monkeypatch):
    module_root = tmp_path / "Vendor" / "Module"
    module_root.mkdir(parents=True)
    monkeypatch.setattr(
        "app.scanner.php_analyzer_client.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient({})
    )

    findings = await check_php_static_analysis(module_root, module_root)

    assert findings == []


def test_relativize_falls_back_to_the_raw_path_when_outside_module_root(tmp_path):
    from app.scanner.php_analyzer_client import _relativize

    module_root = tmp_path / "Vendor" / "Module"
    outside_path = str(Path("/elsewhere/File.php"))

    assert _relativize(outside_path, module_root) == outside_path


def test_pick_php_binary_falls_back_to_the_default_when_nothing_overlaps():
    from app.scanner.php_analyzer_client import _pick_php_binary

    # No installed binary (8.3/8.4/8.5) overlaps a constraint requiring 7.4 only.
    assert _pick_php_binary(">=7.4,<8.0") == "php84"


def test_pick_php_binary_picks_the_highest_overlapping_installed_version():
    from app.scanner.php_analyzer_client import _pick_php_binary

    assert _pick_php_binary(">=8.3.0,<8.4.0") == "php83"


@pytest.mark.asyncio
async def test_check_php_static_analysis_excludes_test_directory_findings(tmp_path, monkeypatch):
    module_root = tmp_path / "Vendor" / "Module"
    module_root.mkdir(parents=True)
    findings_by_tool = {
        "phpstan": [
            {"file": str(module_root / "Test" / "Unit" / "FooTest.php"), "line": 1, "message": "mock stuff"},
            {"file": str(module_root / "Foo.php"), "line": 1, "message": "real finding"},
        ],
    }
    monkeypatch.setattr(
        "app.scanner.php_analyzer_client.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient(findings_by_tool)
    )

    findings = await check_php_static_analysis(module_root, module_root)

    assert len(findings) == 1
    assert findings[0].message == "real finding"


@pytest.mark.asyncio
async def test_check_php_static_analysis_resolves_phpmetrics_class_names_to_file_paths(tmp_path, monkeypatch):
    module_root = tmp_path / "Vendor" / "Module"
    module_root.mkdir(parents=True)
    findings_by_tool = {
        "phpmetrics": [
            {"class": "Vendor\\Module\\Plugin\\SavePlugin", "line": None, "message": "Too complex method code: ..."},
        ],
    }
    monkeypatch.setattr(
        "app.scanner.php_analyzer_client.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient(findings_by_tool)
    )

    findings = await check_php_static_analysis(
        module_root,
        module_root,
        fqcn_to_file={"Vendor\\Module\\Plugin\\SavePlugin": "Plugin/SavePlugin.php"},
    )

    assert len(findings) == 1
    assert findings[0].check_type == "phpmetrics_issue"
    assert findings[0].file_path == "Plugin/SavePlugin.php"
    assert findings[0].severity == "warning"


@pytest.mark.asyncio
async def test_check_php_static_analysis_leaves_a_package_level_phpmetrics_finding_with_no_file(
    tmp_path, monkeypatch
):
    """A package-level rule (e.g. "Stable Dependencies Principle") reports a
    namespace prefix, not a real class -- it never matches a real FQCN, so
    there's correctly no file to point to.
    """
    module_root = tmp_path / "Vendor" / "Module"
    module_root.mkdir(parents=True)
    findings_by_tool = {
        "phpmetrics": [
            {"class": "Vendor\\Module\\Plugin", "line": None, "message": "Stable Dependencies Principle: ..."},
        ],
    }
    monkeypatch.setattr(
        "app.scanner.php_analyzer_client.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient(findings_by_tool)
    )

    findings = await check_php_static_analysis(
        module_root, module_root, fqcn_to_file={"Vendor\\Module\\Plugin\\SavePlugin": "Plugin/SavePlugin.php"}
    )

    assert len(findings) == 1
    assert findings[0].file_path is None


@pytest.mark.asyncio
async def test_check_php_static_analysis_excludes_a_phpmetrics_finding_resolved_to_a_test_file(
    tmp_path, monkeypatch
):
    module_root = tmp_path / "Vendor" / "Module"
    module_root.mkdir(parents=True)
    findings_by_tool = {
        "phpmetrics": [
            {"class": "Vendor\\Module\\Test\\Unit\\FooTest", "line": None, "message": "Probably bugged: ..."},
        ],
    }
    monkeypatch.setattr(
        "app.scanner.php_analyzer_client.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient(findings_by_tool)
    )

    findings = await check_php_static_analysis(
        module_root,
        module_root,
        # Realistic shape: PhpClassEntry.file_path (what fqcn_to_file's real
        # values come from) is already relative to the module root, unlike
        # the absolute paths phpstan/phpmd/phpcs/rector report directly.
        fqcn_to_file={"Vendor\\Module\\Test\\Unit\\FooTest": "Test/Unit/FooTest.php"},
    )

    assert findings == []


@pytest.mark.asyncio
async def test_check_php_static_analysis_fails_open_on_a_non_dict_json_response(tmp_path, monkeypatch):
    class _BareListResponse:
        def raise_for_status(self) -> None:
            pass

        def json(self):
            return ["not", "a", "dict"]

    class _BareListAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None):
            return _BareListResponse()

    module_root = tmp_path / "Vendor" / "Module"
    module_root.mkdir(parents=True)
    monkeypatch.setattr(
        "app.scanner.php_analyzer_client.httpx.AsyncClient", lambda *a, **k: _BareListAsyncClient()
    )

    findings = await check_php_static_analysis(module_root, module_root)

    assert findings == []
