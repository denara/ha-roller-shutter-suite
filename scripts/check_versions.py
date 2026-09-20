"""Guard: the version number is the same everywhere it is written down.

The version exists twice, and both places are needed: Home Assistant and HACS
read ``custom_components/roller_shutter_suite/manifest.json``, and ``uv``
requires a version in ``pyproject.toml``. Neither file can read the other, so
both stay and this script fails when they differ.

**The guard fails closed.** "Could not check" means here, and ends with exit
status 2: one of the two files is missing, unreadable, or cannot be parsed (as
TOML and as a JSON object). A file that states no version, and versions that
differ, end with exit status 1. With 0 the last line names the version that
both files state.

Anything unforeseen inside the script ends with status 2 as well, with the type
of the error only, never its text or a traceback, which may name a local path.

Run it from anywhere: ``python scripts/check_versions.py``. It needs only the
standard library.
"""

import json
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROJECT_FILE = "pyproject.toml"
MANIFEST_FILE = "custom_components/roller_shutter_suite/manifest.json"
EXIT_FINDINGS = 1
EXIT_CANNOT_CHECK = 2


class CannotCheckError(RuntimeError):
    """The guard could not do its job. That is a failure, never a pass."""


def _read(root: Path, name: str) -> str:
    try:
        return (root / name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise CannotCheckError(
            f"{name} cannot be read ({type(error).__name__}). If the file has "
            "moved, change its path in this script"
        ) from error


def _table(content: dict[str, Any], *keys: str) -> dict[str, Any]:
    """Return the nested table ``keys`` name, empty if absent; refuse a non-table."""
    table = content
    for key in keys:
        table = table.get(key, {})
        if not isinstance(table, dict):
            raise CannotCheckError(
                f"'{key}' in {PROJECT_FILE} is not a table, so the file cannot be read "
                "the way this script expects"
            )
    return table


def read_versions(root: Path) -> dict[str, str | None]:
    """Return the version each file states, or ``None`` where it is missing."""
    try:
        project = tomllib.loads(_read(root, PROJECT_FILE))
    except tomllib.TOMLDecodeError as error:
        raise CannotCheckError(f"{PROJECT_FILE} is not valid TOML: {error}") from error
    try:
        manifest = json.loads(_read(root, MANIFEST_FILE))
    except json.JSONDecodeError as error:
        raise CannotCheckError(f"{MANIFEST_FILE} is not valid JSON: {error}") from error
    if not isinstance(manifest, dict):
        raise CannotCheckError(f"{MANIFEST_FILE} is not a JSON object")
    return {
        PROJECT_FILE: _table(project, "project").get("version"),
        MANIFEST_FILE: manifest.get("version"),
    }


def problems(versions: dict[str, str | None]) -> list[str]:
    """Return what is wrong with the versions, empty when they agree."""
    found = [f"{file} states no version" for file, v in versions.items() if not v]
    if not found and len(set(versions.values())) > 1:
        stated = ", ".join(f"{file}: {v}" for file, v in versions.items())
        found.append(f"the versions differ ({stated})")
    return found


def main(root: Path = REPOSITORY_ROOT) -> int:
    """Run the guard on this repository."""
    try:
        versions = read_versions(root)
    except CannotCheckError as error:
        sys.stdout.write(f"versions: CANNOT CHECK, so this is a failure: {error}\n")
        return EXIT_CANNOT_CHECK
    found = problems(versions)
    for problem in found:
        sys.stdout.write(f"versions: {problem}\n")
    if found:
        return EXIT_FINDINGS
    sys.stdout.write(
        f"versions: ok ({next(iter(versions.values()))} in {len(versions)} files)\n"
    )
    return 0


def run(entry: Callable[[], int]) -> int:
    """Run ``entry``; an error nobody foresaw is a failure too, never a pass.

    Only the type of the error is printed. Its text and a traceback may name
    local paths, and the output of this script may be pasted in public.
    """
    try:
        return entry()
    except Exception as error:  # noqa: BLE001 - the net for every unforeseen error
        sys.stdout.write(
            "versions: CANNOT CHECK, so this is a failure: internal error in "
            f"check_versions.py ({type(error).__name__})\n"
        )
        return EXIT_CANNOT_CHECK


if __name__ == "__main__":
    sys.exit(run(main))
