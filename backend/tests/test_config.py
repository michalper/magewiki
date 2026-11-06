from app.config import Settings


def test_scan_roots_empty_when_unconfigured():
    s = Settings(magewiki_scan_root_1="", magewiki_scan_root_2="", magewiki_scan_root_3="")
    assert s.scan_roots == []


def test_scan_roots_filters_blank_slots():
    s = Settings(magewiki_scan_root_1="/srv/repos", magewiki_scan_root_2="", magewiki_scan_root_3="/home/x")
    assert s.scan_roots == ["/srv/repos", "/home/x"]
