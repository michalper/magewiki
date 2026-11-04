from pathlib import Path

from app.scanner.php_classes import catalog_module_classes


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
