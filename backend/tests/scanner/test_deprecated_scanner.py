from app.scanner.deprecated_scanner import scan_deprecated_annotations


def test_scan_deprecated_annotations_flags_only_the_annotated_declaration():
    source = (
        b"<?php\n"
        b"namespace A;\n"
        b"\n"
        b"/**\n"
        b" * @deprecated use Foo instead\n"
        b" */\n"
        b"class Bar {}\n"
        b"\n"
        b"class Baz {}\n"
    )

    findings = scan_deprecated_annotations({"Bar.php": source})

    assert len(findings) == 1
    assert findings[0].check_type == "deprecated_annotation"
    assert findings[0].severity == "warning"
    assert findings[0].file_path == "Bar.php"
    assert "Bar" in findings[0].message


def test_scan_deprecated_annotations_flags_a_deprecated_method():
    source = (
        b"<?php\n"
        b"class Bar {\n"
        b"    /**\n"
        b"     * @deprecated since 2.0\n"
        b"     */\n"
        b"    public function oldMethod() {}\n"
        b"\n"
        b"    public function newMethod() {}\n"
        b"}\n"
    )

    findings = scan_deprecated_annotations({"Bar.php": source})

    assert len(findings) == 1
    assert "oldMethod" in findings[0].message


def test_scan_deprecated_annotations_with_no_annotations():
    assert scan_deprecated_annotations({"Clean.php": b"<?php\nclass Clean {}\n"}) == []
