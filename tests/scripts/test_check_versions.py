"""The version guard compares ``pyproject.toml`` and ``manifest.json``."""

import json
from pathlib import Path

from scripts.check_versions import (
    MANIFEST_FILE,
    PROJECT_FILE,
    problems,
    read_versions,
)


def _write(
    root: Path, project_version: str | None, manifest_version: str | None
) -> None:
    project = "[project]\nname = 'example'\n"
    if project_version is not None:
        project += f"version = '{project_version}'\n"
    (root / PROJECT_FILE).write_text(project, encoding="utf-8")
    manifest = {"domain": "example"}
    if manifest_version is not None:
        manifest["version"] = manifest_version
    (root / MANIFEST_FILE).parent.mkdir(parents=True)
    (root / MANIFEST_FILE).write_text(json.dumps(manifest), encoding="utf-8")


def test_equal_versions_pass(tmp_path: Path) -> None:
    """The same version in both files is fine."""
    _write(tmp_path, "1.2.3", "1.2.3")

    assert problems(read_versions(tmp_path)) == []


def test_different_versions_fail(tmp_path: Path) -> None:
    """A release that was bumped in one file only is caught."""
    _write(tmp_path, "1.2.3", "1.2.4")

    (problem,) = problems(read_versions(tmp_path))

    assert "1.2.3" in problem
    assert "1.2.4" in problem


def test_missing_version_fails(tmp_path: Path) -> None:
    """A file without a version is named."""
    _write(tmp_path, "1.2.3", None)

    (problem,) = problems(read_versions(tmp_path))

    assert MANIFEST_FILE in problem


def test_this_repository_passes() -> None:
    """Both files of this repository state the same version."""
    assert problems(read_versions(Path(__file__).parents[2])) == []
