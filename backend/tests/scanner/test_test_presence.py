from pathlib import Path

from app.scanner.test_presence import has_tests


def test_has_tests_false_when_absent(demo_module_path: Path):
    assert has_tests(demo_module_path) is False


def test_has_tests_true_for_tests_directory(tmp_path: Path):
    (tmp_path / "Test" / "Unit").mkdir(parents=True)
    assert has_tests(tmp_path) is True


def test_has_tests_true_for_test_php_suffix(tmp_path: Path):
    (tmp_path / "SomeClassTest.php").write_text("<?php\n")
    assert has_tests(tmp_path) is True


def test_has_tests_true_for_phpunit_xml(tmp_path: Path):
    (tmp_path / "phpunit.xml.dist").write_text("<phpunit/>\n")
    assert has_tests(tmp_path) is True
