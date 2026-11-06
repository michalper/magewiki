from pathlib import Path

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
