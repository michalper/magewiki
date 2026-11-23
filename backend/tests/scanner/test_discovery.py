import json
import shutil
from pathlib import Path

from app.scanner.discovery import (
    find_modules,
    is_safe_to_read,
    read_module_source_files,
    walk_module_source_files,
)


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


def test_walk_module_source_files_finds_both_classes(demo_module_path: Path):
    files = walk_module_source_files(demo_module_path)
    names = {f.name for f in files}

    assert "SampleCheckoutPlugin.php" in names
    assert "SampleOrderObserver.php" in names


def test_walk_module_source_files_also_finds_phtml_templates(tmp_path: Path):
    (tmp_path / "view/frontend/templates").mkdir(parents=True)
    template = tmp_path / "view/frontend/templates/widget.phtml"
    template.write_text("<?= $block->getData('title') ?>", encoding="utf-8")

    files = walk_module_source_files(tmp_path)

    assert template in files


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


def test_a_composer_path_repository_glob_cannot_escape_repo_root_via_dotdot(
    tmp_path: Path, demo_module_path: Path
):
    """The glob pattern is read verbatim from the scanned repo's own composer.json
    (not operator-controlled) — a realistic monorepo config like "../shared/*"
    (not even an attack) would otherwise let Path.glob() match a module outside
    repo_root entirely, bypassing the scan-root containment boundary enforced at
    the API layer.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True)
    outside = tmp_path / "outside" / "SecretModule"
    shutil.copytree(demo_module_path, outside)
    (repo_root / "composer.json").write_text(
        json.dumps({"repositories": {"local": {"type": "path", "url": "../outside/*"}}})
    )

    discovered = find_modules(repo_root)

    assert discovered == []


def test_an_absolute_composer_path_repository_glob_does_not_crash_the_scan(tmp_path: Path):
    """Composer path repositories support absolute URLs, which make
    Path.glob() raise NotImplementedError — this is a nice-to-have discovery
    aid, per its own docstring, and must never abort the whole scan.
    """
    repo_root = tmp_path / "repo"
    (repo_root / "app" / "code").mkdir(parents=True)
    (repo_root / "composer.json").write_text(
        json.dumps({"repositories": {"local": {"type": "path", "url": "/etc/*"}}})
    )

    discovered = find_modules(repo_root)

    assert discovered == []


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


def test_a_composer_path_repository_glob_skips_a_file_match(tmp_path: Path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "src").mkdir()
    (repo_root / "src" / "NotADirectory").write_text("just a file", encoding="utf-8")
    (repo_root / "composer.json").write_text(
        json.dumps({"repositories": {"local": {"type": "path", "url": "src/*"}}})
    )

    assert find_modules(repo_root) == []


def test_a_composer_path_repository_glob_match_is_skipped_if_resolve_raises_oserror(
    tmp_path: Path, demo_module_path: Path, monkeypatch
):
    repo_root = tmp_path / "repo"
    (repo_root / "src" / "CustomModule").mkdir(parents=True)
    shutil.copytree(demo_module_path, repo_root / "src" / "CustomModule" / "Module")
    (repo_root / "composer.json").write_text(
        json.dumps({"repositories": {"local": {"type": "path", "url": "src/*/*"}}})
    )

    real_resolve = Path.resolve

    def _raise_for_the_match(self, strict=False):
        if self.name == "Module":
            raise OSError("name too long")
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", _raise_for_the_match)

    assert find_modules(repo_root) == []


def test_read_module_source_files_returns_every_files_bytes_keyed_by_relative_path(demo_module_path: Path):
    sources = read_module_source_files(demo_module_path)

    assert set(sources) == {str(f.relative_to(demo_module_path)) for f in walk_module_source_files(demo_module_path)}
    plugin_path = next(rp for rp in sources if rp.endswith("SampleCheckoutPlugin.php"))
    assert sources[plugin_path] == (demo_module_path / plugin_path).read_bytes()


def test_is_safe_to_read_rejects_a_symlink_but_accepts_a_regular_file(tmp_path: Path):
    real = tmp_path / "real.txt"
    real.write_text("content")
    link = tmp_path / "link.txt"
    link.symlink_to(real)

    assert is_safe_to_read(real) is True
    assert is_safe_to_read(link) is False


def test_walk_module_source_files_excludes_a_symlinked_php_file(tmp_path: Path):
    """Security regression: a scanned module is untrusted input (CLAUDE.md).
    A module shipping a symlink named e.g. Evil.php -> /etc/passwd (or any
    host path outside the scanned tree) must never have its *target*'s
    bytes hashed, parsed, or sent to the LLM as "file content to summarize"
    -- confirmed with a real symlink, not a mock, both to a file outside
    the module root and to one of its own real files.
    """
    real = tmp_path / "Real.php"
    real.write_text("<?php\nclass Real {}\n")
    outside_secret = tmp_path.parent / "outside_secret.php"
    outside_secret.write_text("<?php\n// SECRET_API_KEY=supersecret\n")
    (tmp_path / "Evil.php").symlink_to(outside_secret)
    (tmp_path / "SelfLink.php").symlink_to(real)

    files = walk_module_source_files(tmp_path)

    assert files == [real]


def test_read_module_source_files_skips_a_file_that_vanishes_before_it_can_be_read(tmp_path: Path, monkeypatch):
    good = tmp_path / "Good.php"
    good.write_text("<?php\nclass Good {}\n")
    vanished = tmp_path / "Vanished.php"

    monkeypatch.setattr("app.scanner.discovery.walk_module_source_files", lambda root: [good, vanished])

    sources = read_module_source_files(tmp_path)

    assert set(sources) == {"Good.php"}
