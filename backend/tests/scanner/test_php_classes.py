from pathlib import Path

from app.scanner.php_classes import catalog_module_classes, parse_php_file


def test_catalog_module_classes(demo_module_path: Path):
    classes = catalog_module_classes(demo_module_path)
    by_name = {c.class_name: c for c in classes}

    assert "SampleCheckoutPlugin" in by_name
    assert "SampleOrderObserver" in by_name

    plugin = by_name["SampleCheckoutPlugin"]
    assert plugin.namespace == "Vendor\\Module\\Plugin"
    assert plugin.fqcn == "Vendor\\Module\\Plugin\\SampleCheckoutPlugin"
    assert plugin.kind == "class"
    assert plugin.file_path == "Plugin/SampleCheckoutPlugin.php"
    assert {m.name for m in plugin.methods} == {"beforeSubmitAll"}

    observer = by_name["SampleOrderObserver"]
    assert observer.namespace == "Vendor\\Module\\Observer"
    assert observer.implements == ["ObserverInterface"]
    assert {m.name for m in observer.methods} == {"execute"}


def test_parse_php_file_uses_each_class_own_namespace_block(tmp_path: Path):
    # Two braced namespace blocks in one file — each class must get its OWN
    # enclosing namespace, not the file's first one.
    braced = tmp_path / "Braced.php"
    braced.write_text(
        "<?php\n"
        "namespace A {\n"
        "    class Foo {}\n"
        "}\n"
        "namespace B {\n"
        "    class Bar {}\n"
        "}\n"
    )
    entries = {e.class_name: e for e in parse_php_file(braced, "Braced.php")}
    assert entries["Foo"].fqcn == "A\\Foo"
    assert entries["Bar"].fqcn == "B\\Bar"

    # Semicolon-style: a namespace applies to every following declaration up
    # to the next namespace statement, not to the whole file.
    semicolon = tmp_path / "Semicolon.php"
    semicolon.write_text(
        "<?php\n"
        "namespace A;\n"
        "class Foo {}\n"
        "namespace B;\n"
        "class Bar {}\n"
    )
    entries = {e.class_name: e for e in parse_php_file(semicolon, "Semicolon.php")}
    assert entries["Foo"].fqcn == "A\\Foo"
    assert entries["Bar"].fqcn == "B\\Bar"


def test_catalog_module_classes_skips_a_file_that_vanishes_before_it_can_be_read(tmp_path: Path, monkeypatch):
    # A TOCTOU race (the file existed when discovered but is gone by the time it's
    # read) is the realistic way this happens in production; simulated here by
    # having the file list include a path that was never actually written.
    good = tmp_path / "Good.php"
    good.write_text("<?php\nclass Good {}\n")
    vanished = tmp_path / "Vanished.php"

    monkeypatch.setattr("app.scanner.php_classes.walk_module_source_files", lambda root: [good, vanished])

    classes = catalog_module_classes(tmp_path)

    assert {c.class_name for c in classes} == {"Good"}


def test_parse_php_file_captures_a_class_extends_clause(tmp_path: Path):
    path = tmp_path / "Child.php"
    path.write_text("<?php\nclass Child extends ParentClass {}\n")

    entries = parse_php_file(path, "Child.php")

    assert len(entries) == 1
    assert entries[0].extends == ["ParentClass"]


def test_parse_php_file_captures_simple_string_const_declarations(tmp_path: Path):
    path = tmp_path / "Foo.php"
    path.write_text(
        "<?php\n"
        "class Foo {\n"
        "    const ADMIN_RESOURCE = 'Vendor_Module::foo';\n"
        "    const EMPTY = '';\n"
        "    const NOT_A_STRING = 1;\n"
        "    const NOT_RESOLVABLE = self::ADMIN_RESOURCE;\n"
        "}\n"
    )

    entries = parse_php_file(path, "Foo.php")

    assert len(entries) == 1
    assert entries[0].consts == {"ADMIN_RESOURCE": "Vendor_Module::foo", "EMPTY": ""}


def test_parse_php_file_captures_abstract_modifier(tmp_path: Path):
    path = tmp_path / "Foo.php"
    path.write_text("<?php\nabstract class Foo {}\nclass Bar {}\n")

    entries = {e.class_name: e for e in parse_php_file(path, "Foo.php")}

    assert entries["Foo"].is_abstract is True
    assert entries["Bar"].is_abstract is False
