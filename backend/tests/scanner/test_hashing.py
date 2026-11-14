import hashlib
from pathlib import Path

from app.scanner.hashing import (
    FileDiff,
    aggregate_hash,
    compute_module_file_hashes,
    diff_file_hashes,
)


def test_compute_module_file_hashes_includes_present_fixed_files_and_source_files(demo_module_path: Path):
    hashes = compute_module_file_hashes(demo_module_path)

    # demo-store's Vendor_Module ships 4 of the 5 _FIXED_FILES (no
    # schema.graphqls) plus every .php file walk_module_source_files finds --
    # that's suffix-only matching, so registration.php counts too, same as
    # any other class file.
    assert set(hashes) == {
        "etc/module.xml",
        "composer.json",
        "etc/di.xml",
        "etc/events.xml",
        "registration.php",
        "Observer/SampleOrderObserver.php",
        "Plugin/SampleCheckoutPlugin.php",
    }


def test_compute_module_file_hashes_skips_a_fixed_file_that_does_not_exist(demo_module_path: Path):
    hashes = compute_module_file_hashes(demo_module_path)

    assert "etc/schema.graphqls" not in hashes


def test_compute_module_file_hashes_matches_a_direct_sha256_of_the_file_content(demo_module_path: Path):
    hashes = compute_module_file_hashes(demo_module_path)

    expected = hashlib.sha256((demo_module_path / "composer.json").read_bytes()).hexdigest()
    assert hashes["composer.json"] == expected


def test_compute_module_file_hashes_registers_a_source_file_under_its_nested_relative_path(tmp_path: Path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "module.xml").write_text("<config/>", encoding="utf-8")
    nested = tmp_path / "Block" / "Deeply" / "Nested"
    nested.mkdir(parents=True)
    (nested / "Widget.php").write_text("<?php class Widget {}", encoding="utf-8")

    hashes = compute_module_file_hashes(tmp_path)

    assert set(hashes) == {"etc/module.xml", "Block/Deeply/Nested/Widget.php"}


def test_aggregate_hash_is_independent_of_dict_insertion_order():
    # The cache key (content_hash) this feeds into (app/analyzer cache, see
    # CLAUDE.md) must be stable regardless of os.walk()'s own, unspecified
    # directory-entry order -- aggregate_hash's sorted() call is what
    # guarantees that, and this is the regression test for it.
    a = {"b.php": "1", "a.php": "2"}
    b = {"a.php": "2", "b.php": "1"}

    assert aggregate_hash(a) == aggregate_hash(b)


def test_aggregate_hash_changes_when_any_file_content_changes():
    base = {"a.php": "1", "b.php": "2"}
    changed = {"a.php": "1", "b.php": "different"}

    assert aggregate_hash(base) != aggregate_hash(changed)


def test_aggregate_hash_changes_when_a_path_is_added_or_removed():
    base = {"a.php": "1"}
    with_extra = {"a.php": "1", "b.php": "2"}

    assert aggregate_hash(base) != aggregate_hash(with_extra)


def test_aggregate_hash_of_an_empty_mapping_is_deterministic():
    assert aggregate_hash({}) == hashlib.sha256(b"").hexdigest()


def test_aggregate_hash_matches_the_sorted_path_digest_line_format():
    hashes = {"b.php": "hashb", "a.php": "hasha"}
    expected = hashlib.sha256(b"a.php:hasha\nb.php:hashb\n").hexdigest()

    assert aggregate_hash(hashes) == expected


def test_diff_file_hashes_classifies_added_changed_removed_and_ignores_unchanged():
    old = {"unchanged": "1", "changed": "old", "removed": "1"}
    new = {"unchanged": "1", "changed": "new", "added": "1"}

    diff = diff_file_hashes(old, new)

    assert diff.added == ["added"]
    assert diff.changed == ["changed"]
    assert diff.removed == ["removed"]


def test_diff_file_hashes_result_lists_are_sorted():
    diff = diff_file_hashes({}, {"z.php": "1", "a.php": "1", "m.php": "1"})

    assert diff.added == ["a.php", "m.php", "z.php"]


def test_file_diff_is_empty_true_when_nothing_changed():
    assert FileDiff().is_empty()
    assert diff_file_hashes({"a.php": "1"}, {"a.php": "1"}).is_empty()


def test_file_diff_is_empty_false_when_anything_changed():
    assert not diff_file_hashes({}, {"a.php": "1"}).is_empty()
    assert not diff_file_hashes({"a.php": "1"}, {}).is_empty()
    assert not diff_file_hashes({"a.php": "1"}, {"a.php": "2"}).is_empty()
