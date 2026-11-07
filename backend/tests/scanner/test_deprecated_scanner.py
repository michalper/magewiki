from pathlib import Path

from app.scanner.deprecated_scanner import scan_deprecated_annotations


def test_scan_deprecated_annotations_flags_only_the_annotated_declaration(tmp_path: Path):
    (tmp_path / "Bar.php").write_text(
        "<?php\n"
        "namespace A;\n"
        "\n"
        "/**\n"
        " * @deprecated use Foo instead\n"
        " */\n"
        "class Bar {}\n"
        "\n"
        "class Baz {}\n"
    )

    findings = scan_deprecated_annotations(tmp_path)

    assert len(findings) == 1
    assert findings[0].check_type == "deprecated_annotation"
    assert findings[0].severity == "warning"
    assert findings[0].file_path == "Bar.php"
    assert "Bar" in findings[0].message


def test_scan_deprecated_annotations_flags_a_deprecated_method(tmp_path: Path):
    (tmp_path / "Bar.php").write_text(
        "<?php\n"
        "class Bar {\n"
        "    /**\n"
        "     * @deprecated since 2.0\n"
        "     */\n"
        "    public function oldMethod() {}\n"
        "\n"
        "    public function newMethod() {}\n"
        "}\n"
    )

    findings = scan_deprecated_annotations(tmp_path)

    assert len(findings) == 1
    assert "oldMethod" in findings[0].message


def test_scan_deprecated_annotations_with_no_annotations(tmp_path: Path):
    (tmp_path / "Clean.php").write_text("<?php\nclass Clean {}\n")
    assert scan_deprecated_annotations(tmp_path) == []


def test_scan_deprecated_annotations_skips_a_file_that_vanishes_before_it_can_be_read(tmp_path: Path, monkeypatch):
    clean = tmp_path / "Clean.php"
    clean.write_text("<?php\nclass Clean {}\n")
    vanished = tmp_path / "Vanished.php"

    monkeypatch.setattr("app.scanner.deprecated_scanner.walk_module_source_files", lambda root: [clean, vanished])

    assert scan_deprecated_annotations(tmp_path) == []
