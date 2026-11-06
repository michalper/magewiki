from pathlib import Path

from app.scanner.readme_check import has_readme


def test_has_readme_false_when_absent(demo_module_path: Path):
    assert has_readme(demo_module_path) is False


def test_has_readme_true_for_readme_md(tmp_path: Path):
    (tmp_path / "README.md").write_text("# A module\n")
    assert has_readme(tmp_path) is True


def test_has_readme_false_for_empty_file(tmp_path: Path):
    (tmp_path / "README.md").write_text("")
    assert has_readme(tmp_path) is False


def test_has_readme_true_for_readme_txt(tmp_path: Path):
    (tmp_path / "README.txt").write_text("A module.\n")
    assert has_readme(tmp_path) is True
