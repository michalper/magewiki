import uuid

import pytest

from app.scanner.abandoned_dependencies import _latest_version_entry, check_abandoned_outdated


class _FakeResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code

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
        package = url.split("/p2/", 1)[1].removesuffix(".json")
        self.calls.append(package)
        if package not in self._data_by_package:
            return _FakeResponse({}, status_code=404)
        return _FakeResponse({"packages": {package: self._data_by_package[package]}})


@pytest.mark.asyncio
async def test_check_abandoned_outdated_handles_multiple_cache_misses_concurrently(db_session, monkeypatch):
    """Regression test for the batch-then-gather-then-write redesign: several
    packages all missing from cache in one call must each get their own
    correctly-matched data, not mixed up or dropped, when fetched concurrently
    rather than one at a time. One of them 404s (no P2 entry at all) and must
    not break the others.
    """
    suffix = uuid.uuid4().hex[:8]
    packages = [f"vendor/pkg-{suffix}-{i}" for i in range(3)]
    data = {
        packages[0]: [{"version": "2.0.0", "abandoned": "vendor/successor"}],
        packages[1]: [{"version": "3.0.0", "abandoned": False}],
        # packages[2] deliberately omitted -> 404
    }
    monkeypatch.setattr(
        "app.scanner.abandoned_dependencies.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient(data)
    )

    findings = await check_abandoned_outdated(db_session, {p: "^1.0" for p in packages})

    by_type = {f.check_type: f.message for f in findings}
    assert "vendor/successor" in by_type["abandoned_dependency"]
    assert "3.0.0" in by_type["outdated_dependency"]
    assert len(findings) == 2  # packages[2]'s 404 contributed nothing, didn't error


@pytest.mark.asyncio
async def test_check_abandoned_outdated_flags_an_abandoned_package(db_session, monkeypatch):
    package = f"vendor/pkg-{uuid.uuid4().hex[:8]}"
    data = {package: [{"version": "2.0.0", "abandoned": "vendor/successor"}]}
    monkeypatch.setattr(
        "app.scanner.abandoned_dependencies.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient(data)
    )

    findings = await check_abandoned_outdated(db_session, {package: "^1.0"})

    assert len(findings) == 1
    assert findings[0].check_type == "abandoned_dependency"
    assert findings[0].severity == "warning"
    assert "vendor/successor" in findings[0].message


@pytest.mark.asyncio
async def test_check_abandoned_outdated_flags_an_outdated_constraint(db_session, monkeypatch):
    package = f"vendor/pkg-{uuid.uuid4().hex[:8]}"
    data = {package: [{"version": "3.0.0", "abandoned": False}]}
    monkeypatch.setattr(
        "app.scanner.abandoned_dependencies.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient(data)
    )

    findings = await check_abandoned_outdated(db_session, {package: "^1.0"})

    assert len(findings) == 1
    assert findings[0].check_type == "outdated_dependency"
    assert "3.0.0" in findings[0].message


@pytest.mark.asyncio
async def test_check_abandoned_outdated_clean_when_latest_satisfies_constraint(db_session, monkeypatch):
    package = f"vendor/pkg-{uuid.uuid4().hex[:8]}"
    data = {package: [{"version": "1.4.0", "abandoned": False}]}
    monkeypatch.setattr(
        "app.scanner.abandoned_dependencies.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient(data)
    )

    findings = await check_abandoned_outdated(db_session, {package: "^1.0"})

    assert findings == []


@pytest.mark.asyncio
async def test_check_abandoned_outdated_skips_a_prerelease_listed_ahead_of_the_latest_stable(
    db_session, monkeypatch
):
    """Real bug found via live Packagist data: the P2 API lists versions newest-first
    with NO stability filtering — e.g. symfony/console's response lists a beta ahead
    of the true latest stable release. Taking versions[0] unfiltered produces a false
    outdated_dependency finding for a module already on the newest stable release.
    """
    package = f"vendor/pkg-{uuid.uuid4().hex[:8]}"
    data = {
        package: [
            {"version": "v8.2.0-BETA1", "abandoned": False},
            {"version": "v8.1.11", "abandoned": False},
        ]
    }
    monkeypatch.setattr(
        "app.scanner.abandoned_dependencies.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient(data)
    )

    findings = await check_abandoned_outdated(db_session, {package: "^8.1"})

    assert findings == []  # ^8.1 is satisfied by the real latest stable, v8.1.11


def test_latest_version_entry_falls_back_to_the_newest_when_every_release_is_a_prerelease():
    versions = [{"version": "v1.0.0-alpha2"}, {"version": "v1.0.0-alpha1"}]
    entry = _latest_version_entry("vendor/pkg", {"packages": {"vendor/pkg": versions}})

    # Nothing stable exists yet — falls back to the newest (first-listed) entry
    # rather than reporting no "latest version" at all for a brand-new package.
    assert entry is not None
    assert entry["version"] == "v1.0.0-alpha2"


@pytest.mark.asyncio
async def test_check_abandoned_outdated_skips_an_unknown_package(db_session, monkeypatch):
    package = f"vendor/pkg-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(
        "app.scanner.abandoned_dependencies.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient({})
    )

    findings = await check_abandoned_outdated(db_session, {package: "^1.0"})

    assert findings == []


@pytest.mark.asyncio
async def test_check_abandoned_outdated_skips_a_package_with_no_versions_listed(db_session, monkeypatch):
    package = f"vendor/pkg-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(
        "app.scanner.abandoned_dependencies.httpx.AsyncClient", lambda *a, **k: _FakeAsyncClient({package: []})
    )

    findings = await check_abandoned_outdated(db_session, {package: "^1.0"})

    assert findings == []


@pytest.mark.asyncio
async def test_check_abandoned_outdated_uses_the_cache_on_a_second_call(db_session, monkeypatch):
    package = f"vendor/pkg-{uuid.uuid4().hex[:8]}"
    data = {package: [{"version": "2.0.0"}]}
    client = _FakeAsyncClient(data)
    monkeypatch.setattr("app.scanner.abandoned_dependencies.httpx.AsyncClient", lambda *a, **k: client)

    await check_abandoned_outdated(db_session, {package: "^1.0"})
    assert client.calls == [package]

    await check_abandoned_outdated(db_session, {package: "^1.0"})

    assert client.calls == [package]  # no second HTTP call -- the cache row served it


@pytest.mark.asyncio
async def test_fetch_from_packagist_returns_none_on_an_http_error(db_session, monkeypatch):
    import httpx

    class _RaisingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("app.scanner.abandoned_dependencies.httpx.AsyncClient", lambda *a, **k: _RaisingClient())

    package = f"vendor/pkg-{uuid.uuid4().hex[:8]}"
    findings = await check_abandoned_outdated(db_session, {package: "^1.0"})

    assert findings == []
