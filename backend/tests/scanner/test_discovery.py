import json
import shutil
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


def test_find_modules_discovers_a_module_via_a_composer_path_repository(
    tmp_path: Path, demo_module_path: Path
):
    """Real-world gap: a store's own custom modules are sometimes installed
    via a Composer "path" repository pointing outside app/code and vendor
    entirely (e.g. a monorepo-style `src/` directory) — invisible to a scan
    that only ever walks those two directories.
    """
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "CustomModule").mkdir(parents=True)
    shutil.copytree(demo_module_path, repo_root / "src" / "CustomModule" / "Module")
    (repo_root / "composer.json").write_text(
        json.dumps({"repositories": {"local": {"type": "path", "url": "src/*/*"}}})
    )

    discovered = find_modules(repo_root)

    assert len(discovered) == 1
    assert discovered[0].source_type == "composer_path"
    assert discovered[0].relative_path == Path("src/CustomModule/Module")


def test_find_modules_is_not_confused_by_an_unrelated_vendor_symlink_to_the_same_module(
    tmp_path: Path, demo_module_path: Path
):
    """A path-repository directory is sometimes *also* symlinked into
    vendor/ once `composer install` has actually run. This doesn't currently
    risk double-discovery by itself — os.walk()'s default followlinks=False
    means it never visits a symlinked directory as a dirpath, so the
    vendor/ walk can't find it that way regardless — but confirms the
    resolved-path dedup is at least harmless/correct when such a symlink is
    present alongside the real path-repository directory.
    """
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "CustomModule").mkdir(parents=True)
    real_module = repo_root / "src" / "CustomModule" / "Module"
    shutil.copytree(demo_module_path, real_module)
    (repo_root / "composer.json").write_text(
        json.dumps({"repositories": {"local": {"type": "path", "url": "src/*/*"}}})
    )

    (repo_root / "vendor" / "vendor-ns").mkdir(parents=True)
    (repo_root / "vendor" / "vendor-ns" / "module").symlink_to(real_module, target_is_directory=True)

    discovered = find_modules(repo_root)

    assert len(discovered) == 1
    assert discovered[0].source_type == "composer_path"
