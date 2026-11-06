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
