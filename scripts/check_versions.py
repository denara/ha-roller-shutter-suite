"""Guard: the version number is the same everywhere it is written down.

The version exists twice, and both places are needed: Home Assistant and HACS
read ``custom_components/roller_shutter_suite/manifest.json``, and ``uv``
requires a version in ``pyproject.toml``. Neither file can read the other, so
both stay and this script fails when they differ.

Run it from anywhere: ``python scripts/check_versions.py``. It needs only the
standard library.
"""

import json
import sys
import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PROJECT_FILE = "pyproject.toml"
MANIFEST_FILE = "custom_components/roller_shutter_suite/manifest.json"


def read_versions(root: Path) -> dict[str, str | None]:
    """Return the version each file states, or ``None`` where it is missing."""
    project = tomllib.loads((root / PROJECT_FILE).read_text(encoding="utf-8"))
    manifest = json.loads((root / MANIFEST_FILE).read_text(encoding="utf-8"))
    return {
        PROJECT_FILE: project.get("project", {}).get("version"),
        MANIFEST_FILE: manifest.get("version"),
    }


def problems(versions: dict[str, str | None]) -> list[str]:
    """Return what is wrong with the versions, empty when they agree."""
    found = [f"{file} states no version" for file, v in versions.items() if not v]
    if not found and len(set(versions.values())) > 1:
        stated = ", ".join(f"{file}: {v}" for file, v in versions.items())
        found.append(f"the versions differ ({stated})")
    return found


def main() -> int:
    """Run the guard on this repository."""
    versions = read_versions(REPOSITORY_ROOT)
    found = problems(versions)
    for problem in found:
        sys.stdout.write(f"versions: {problem}\n")
    if found:
        return 1
    sys.stdout.write(f"versions: ok ({next(iter(versions.values()))})\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
