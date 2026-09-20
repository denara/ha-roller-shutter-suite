"""No guard takes a folder it cannot read for an empty one.

``Path.rglob`` passes over an unreadable folder without a word, and
``Path.exists`` answers ``False`` for every error of the operating system. A
guard built on them would check fewer files and still pass. Every guard that
searches folders is tried here with a folder that refuses to be listed and
with a required file that refuses to be examined.
"""

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from scripts import (
    check_core_purity,
    check_coverage,
    check_coverage_exclusions,
    check_deprecated_names,
    check_foreign_warnings,
    check_log_guard,
)

FILES = (
    "pyproject.toml",
    "custom_components/roller_shutter_suite/__init__.py",
    "custom_components/roller_shutter_suite/core/__init__.py",
    "custom_components/roller_shutter_suite/core/locked/module.py",
    "custom_components/roller_shutter_suite/locked/module.py",
    "tests/ha/conftest.py",
    "tests/ha/test_report_guard.py",
    "tests/locked/test_module.py",
    "scripts/module.py",
    "scripts/locked/module.py",
    ".github/workflows/test.yml",
)
SEARCHES: dict[str, tuple[Callable[[Path], object], type[Exception]]] = {
    "check_core_purity": (
        check_core_purity.core_files,
        check_core_purity.CannotCheckError,
    ),
    "check_coverage": (
        lambda root: check_coverage.unmeasured_files(root, {}),
        check_coverage.CannotCheckError,
    ),
    "check_coverage_exclusions": (
        check_coverage_exclusions.scanned_files,
        check_coverage_exclusions.CannotCheckError,
    ),
    "check_deprecated_names": (
        check_deprecated_names.scanned_files,
        check_deprecated_names.CannotCheckError,
    ),
    "check_foreign_warnings": (
        check_foreign_warnings.own_module_names,
        check_foreign_warnings.CannotCheckError,
    ),
    "check_log_guard": (check_log_guard.inputs, check_log_guard.CannotCheckError),
}


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Return a tree in which every guard finds what it searches for."""
    for name in FILES:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(
            "VALUE = 1\n" if name.endswith(".py") else "", "utf-8"
        )
    return tmp_path


def test_every_guard_that_searches_folders_is_tried() -> None:
    """The two scripts left out read named files only and search no folder."""
    scripts = Path(__file__).parents[2] / "scripts"
    searching = {
        file.stem
        for file in scripts.glob("*.py")
        if "os.walk(" in file.read_text(encoding="utf-8")
    }

    assert searching == set(SEARCHES)
    for file in scripts.glob("*.py"):
        text = file.read_text(encoding="utf-8")
        for swallowing in ("glob(", ".exists()", ".is_file()", ".is_symlink()"):
            assert swallowing not in text, f"{file.name} uses {swallowing}"


@pytest.mark.parametrize("script", sorted(SEARCHES))
def test_complete_tree_is_searched(script: str, tree: Path) -> None:
    """The counterpart: with nothing refused, the search succeeds."""
    search, _error = SEARCHES[script]

    assert search(tree)


@pytest.mark.parametrize("script", sorted(SEARCHES))
def test_folder_that_cannot_be_listed_is_a_failure(
    script: str, tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Forced on every platform: listing a folder called ``locked`` is refused."""
    search, error = SEARCHES[script]
    original = os.scandir

    def scandir(path: str) -> Iterator[os.DirEntry[str]]:
        if Path(path).name == "locked":
            raise PermissionError(13, "refused for the test", path)
        return original(path)

    monkeypatch.setattr(os, "scandir", scandir)

    with pytest.raises(error, match=r"cannot be listed \(PermissionError\)"):
        search(tree)


CAN_LOCK_FOLDERS = os.name == "posix" and getattr(os, "geteuid", lambda: 0)() != 0


@pytest.mark.skipif(
    not CAN_LOCK_FOLDERS, reason="permissions cannot be taken away here"
)
@pytest.mark.parametrize("script", sorted(SEARCHES))
def test_folder_without_permission_is_a_failure(script: str, tree: Path) -> None:
    """The real case. Skipped where a folder cannot be locked (Windows, root).

    Nothing is hidden by the skip: the test above forces the same refusal on
    every platform, and this one runs on Linux, which is where CI runs.
    """
    search, error = SEARCHES[script]
    locked = [folder for folder in tree.rglob("locked") if folder.is_dir()]
    for folder in locked:
        folder.chmod(0)
    try:
        with pytest.raises(error, match="cannot be listed"):
            search(tree)
    finally:
        for folder in locked:
            folder.chmod(0o700)


def test_required_file_that_cannot_be_examined_is_not_taken_for_missing(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A configuration file that would override the project must not hide."""
    original = Path.lstat

    def lstat(path: Path) -> os.stat_result:
        if path.name in {"pytest.ini", ".coveragerc"}:
            raise PermissionError(13, "refused for the test", str(path))
        return original(path)

    monkeypatch.setattr(Path, "lstat", lstat)

    with pytest.raises(check_log_guard.CannotCheckError, match="cannot be examined"):
        check_log_guard.check_tree(tree)
    with pytest.raises(
        check_coverage_exclusions.CannotCheckError, match="cannot be examined"
    ):
        check_coverage_exclusions.other_configuration_files(tree)
