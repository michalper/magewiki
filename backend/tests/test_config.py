from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_scan_roots_empty_when_unconfigured():
    s = Settings(magewiki_scan_root_1="", magewiki_scan_root_2="", magewiki_scan_root_3="")
    assert s.scan_roots == []


def test_scan_roots_filters_blank_slots():
    s = Settings(magewiki_scan_root_1="/srv/repos", magewiki_scan_root_2="", magewiki_scan_root_3="/home/x")
    assert s.scan_roots == ["/srv/repos", "/home/x"]


def test_is_within_scan_roots_accepts_the_root_itself(tmp_path: Path):
    s = Settings(magewiki_scan_root_1=str(tmp_path), magewiki_scan_root_2="", magewiki_scan_root_3="")
    assert s.is_within_scan_roots(str(tmp_path)) is True


def test_is_within_scan_roots_accepts_a_descendant(tmp_path: Path):
    child = tmp_path / "store-a" / "app" / "code"
    child.mkdir(parents=True)
    s = Settings(magewiki_scan_root_1=str(tmp_path), magewiki_scan_root_2="", magewiki_scan_root_3="")
    assert s.is_within_scan_roots(str(child)) is True


def test_is_within_scan_roots_rejects_a_sibling_directory(tmp_path: Path):
    allowed = tmp_path / "allowed"
    sibling = tmp_path / "not-allowed"
    allowed.mkdir()
    sibling.mkdir()
    s = Settings(magewiki_scan_root_1=str(allowed), magewiki_scan_root_2="", magewiki_scan_root_3="")
    assert s.is_within_scan_roots(str(sibling)) is False


def test_is_within_scan_roots_rejects_everything_when_unconfigured(tmp_path: Path):
    """Fail closed, not fail open — no scan roots configured must mean nothing is
    scannable, not "any path the process can see is fair game."
    """
    s = Settings(magewiki_scan_root_1="", magewiki_scan_root_2="", magewiki_scan_root_3="")
    assert s.is_within_scan_roots(str(tmp_path)) is False


def test_is_within_scan_roots_resolves_dot_dot_traversal(tmp_path: Path):
    allowed = tmp_path / "allowed"
    sibling = tmp_path / "not-allowed"
    allowed.mkdir()
    sibling.mkdir()
    s = Settings(magewiki_scan_root_1=str(allowed), magewiki_scan_root_2="", magewiki_scan_root_3="")
    traversal_path = str(allowed / ".." / "not-allowed")
    assert s.is_within_scan_roots(traversal_path) is False


def test_license_risk_prefix_tuple_parses_the_default():
    s = Settings(license_risk_prefixes="GPL-,AGPL-,SSPL-")
    assert s.license_risk_prefix_tuple == ("GPL-", "AGPL-", "SSPL-")


def test_license_risk_prefix_tuple_uppercases_and_strips_whitespace():
    s = Settings(license_risk_prefixes=" gpl-, lgpl- ")
    assert s.license_risk_prefix_tuple == ("GPL-", "LGPL-")


def test_license_risk_prefix_tuple_empty_when_unconfigured():
    s = Settings(license_risk_prefixes="")
    assert s.license_risk_prefix_tuple == ()


@pytest.mark.parametrize("field", ["webhook_hmac_secret", "write_access_token"])
def test_secret_fields_accept_empty_disabled_value(field):
    s = Settings(**{field: ""})
    assert getattr(s, field) == ""


@pytest.mark.parametrize("field", ["webhook_hmac_secret", "write_access_token"])
def test_secret_fields_accept_a_16_character_secret(field):
    s = Settings(**{field: "a" * 16})
    assert getattr(s, field) == "a" * 16


@pytest.mark.parametrize("field", ["webhook_hmac_secret", "write_access_token"])
def test_secret_fields_reject_a_too_short_secret(field):
    """OpenSSF Best Practices Badge's crypto_keylength criterion: a configured
    secret must meet a minimum length, not just "non-empty" -- empty (disabled)
    stays allowed, matching this project's own established convention."""
    with pytest.raises(ValidationError, match=f"{field} must be empty"):
        Settings(**{field: "short"})


@pytest.mark.parametrize("bad_path", [123, ["x"], {"a": 1}, None])
def test_is_within_scan_roots_fails_closed_for_a_non_string_path(tmp_path: Path, bad_path):
    """POST /webhooks/scan's `path` comes from untrusted JSON, not a
    Pydantic-validated field -- a non-string value reaches here as-is, and
    Path() raises TypeError for it, not OSError. Found by a whole-project
    code review: must fail closed (return False), not propagate as an
    unhandled 500."""
    s = Settings(magewiki_scan_root_1=str(tmp_path), magewiki_scan_root_2="", magewiki_scan_root_3="")
    assert s.is_within_scan_roots(bad_path) is False


def test_is_within_scan_roots_fails_closed_when_resolve_raises_oserror(tmp_path: Path, monkeypatch):
    """Path.resolve() can raise OSError for a real, pathological input (e.g. a
    component exceeding the filesystem's max name length) -- must fail closed
    (reject), not propagate the exception out of an access-control check.
    """
    def _raise(self, strict=False):
        raise OSError("name too long")

    monkeypatch.setattr(Path, "resolve", _raise)

    s = Settings(magewiki_scan_root_1=str(tmp_path), magewiki_scan_root_2="", magewiki_scan_root_3="")
    assert s.is_within_scan_roots(str(tmp_path)) is False
