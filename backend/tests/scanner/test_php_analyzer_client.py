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

    findings = await check_php_static_analysis(module_root)

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

    findings = await check_php_static_analysis(module_root)

    assert findings == []


@pytest.mark.asyncio
async def test_check_php_static_analysis_with_no_findings(tmp_path, monkeypatch):
    module_root = tmp_path / "Vendor" / "Module"
    module_root.mkdir(parents=True)
    monkeypatch.setattr(
        "app.scanner.php_analyzer_client.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient({})
    )

    findings = await check_php_static_analysis(module_root)

    assert findings == []


def test_relativize_falls_back_to_the_raw_path_when_outside_module_root(tmp_path):
    from app.scanner.php_analyzer_client import _relativize

    module_root = tmp_path / "Vendor" / "Module"
    outside_path = str(Path("/elsewhere/File.php"))

    assert _relativize(outside_path, module_root) == outside_path
