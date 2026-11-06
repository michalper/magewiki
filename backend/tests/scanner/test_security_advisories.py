import uuid

import pytest

from app.scanner.security_advisories import check_security_advisories


class _FakeResponse:
    def __init__(self, json_data: dict):
        self._json = json_data

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._json


class _FakeAsyncClient:
    def __init__(self, data_by_package: dict, *args, **kwargs):
        self._data_by_package = data_by_package
        self.calls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None):
        package = params["packages[]"]
        self.calls.append(package)
        return _FakeResponse({"advisories": {package: self._data_by_package.get(package, [])}})


@pytest.mark.asyncio
async def test_check_security_advisories_flags_an_overlapping_vulnerable_range(db_session, monkeypatch):
    package = f"vendor/pkg-{uuid.uuid4().hex[:8]}"
    advisories = {
        package: [
            {
                "cve": "CVE-2024-0001",
                "title": "Something bad",
                "link": "https://example.com/advisory",
                "affectedVersions": ">=1.0,<1.5",
            }
        ]
    }
    monkeypatch.setattr(
        "app.scanner.security_advisories.httpx.AsyncClient",
        lambda *a, **k: _FakeAsyncClient(advisories),
    )

    findings = await check_security_advisories(db_session, {package: "^1.0"})

    assert len(findings) == 1
    assert findings[0].check_type == "security_advisory"
    assert findings[0].severity == "blocking"
    assert "CVE-2024-0001" in findings[0].message
    assert "https://example.com/advisory" in findings[0].message


@pytest.mark.asyncio
async def test_check_security_advisories_ignores_a_non_overlapping_advisory(db_session, monkeypatch):
    package = f"vendor/pkg-{uuid.uuid4().hex[:8]}"
    advisories = {package: [{"cve": "CVE-2024-0002", "title": "Old bug", "affectedVersions": ">=0.1,<0.5"}]}
    monkeypatch.setattr(
        "app.scanner.security_advisories.httpx.AsyncClient",
        lambda *a, **k: _FakeAsyncClient(advisories),
    )

    findings = await check_security_advisories(db_session, {package: "^1.0"})

    assert findings == []


@pytest.mark.asyncio
async def test_check_security_advisories_handles_multiple_cache_misses_concurrently(db_session, monkeypatch):
    """Regression test for the batch-then-gather-then-write redesign: several
    packages all missing from cache in one call must each get their own
    correctly-matched advisories, not mixed up or dropped, when fetched
    concurrently rather than one at a time.
    """
    suffix = uuid.uuid4().hex[:8]
    packages = [f"vendor/pkg-{suffix}-{i}" for i in range(4)]
    advisories = {
        packages[0]: [{"cve": "CVE-A", "title": "A", "affectedVersions": ">=1.0,<1.5"}],
        packages[2]: [{"cve": "CVE-C", "title": "C", "affectedVersions": ">=1.0,<1.5"}],
    }
    monkeypatch.setattr(
        "app.scanner.security_advisories.httpx.AsyncClient",
        lambda *a, **k: _FakeAsyncClient(advisories),
    )

    findings = await check_security_advisories(db_session, {p: "^1.0" for p in packages})

    assert {f.message.split(" — ")[0] for f in findings} == {"CVE-A", "CVE-C"}


@pytest.mark.asyncio
async def test_check_security_advisories_caches_the_response(db_session, monkeypatch):
    package = f"vendor/pkg-{uuid.uuid4().hex[:8]}"
    client = _FakeAsyncClient({})
    monkeypatch.setattr("app.scanner.security_advisories.httpx.AsyncClient", lambda *a, **k: client)

    await check_security_advisories(db_session, {package: "^1.0"})
    await check_security_advisories(db_session, {package: "^1.0"})

    assert client.calls == [package]
