from pathlib import Path

from app.scanner.discovery import find_modules, walk_module_php_files


def test_find_modules_in_store_root(demo_store_path: Path):
    discovered = find_modules(demo_store_path)

    assert len(discovered) == 1
    module = discovered[0]
    assert module.source_type == "app_code"
    assert module.relative_path == Path("app/code/Vendor/Module")


def test_find_modules_standalone(demo_module_path: Path):
    discovered = find_modules(demo_module_path)

    assert len(discovered) == 1
    assert discovered[0].source_type == "standalone"
    assert discovered[0].relative_path == Path(".")


def test_walk_module_php_files_finds_both_classes(demo_module_path: Path):
    files = walk_module_php_files(demo_module_path)
    names = {f.name for f in files}

    assert "SampleCheckoutPlugin.php" in names
    assert "SampleOrderObserver.php" in names
