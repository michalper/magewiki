import shutil
from pathlib import Path

from app.scanner.multi_store import find_store_roots


def test_a_store_root_itself_is_returned_as_is(demo_store_path: Path):
    assert find_store_roots(demo_store_path) == [demo_store_path]


def test_a_standalone_module_root_itself_is_returned_as_is(demo_module_path: Path):
    assert find_store_roots(demo_module_path) == [demo_module_path]


def test_a_container_directory_returns_its_store_shaped_children_sorted(
    tmp_path: Path, demo_store_path: Path
):
    """On a real server, several stores commonly live side by side under one
    parent directory (e.g. /sites/store-a, /sites/store-b, ...) — this is the
    "scan all of them in one go" discovery step.
    """
    container = tmp_path / "sites"
    container.mkdir()
    shutil.copytree(demo_store_path, container / "store-b")
    shutil.copytree(demo_store_path, container / "store-a")
    (container / "not-a-store").mkdir()  # e.g. logs/backups — must be skipped, not errored

    roots = find_store_roots(container)

    assert [r.name for r in roots] == ["store-a", "store-b"]


def test_a_directory_with_no_store_shaped_children_returns_empty_list(tmp_path: Path):
    unrelated = tmp_path / "unrelated"
    (unrelated / "some-random-folder").mkdir(parents=True)

    assert find_store_roots(unrelated) == []


def test_a_nonexistent_path_returns_empty_list(tmp_path: Path):
    assert find_store_roots(tmp_path / "does-not-exist") == []
