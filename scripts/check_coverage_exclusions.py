"""Guard: code is excluded from coverage only openly and with a reason.

The coverage thresholds (``scripts/check_coverage.py``) exist because an
untested code path is where a deprecation hides. They are worth nothing if code
can be taken out of the measurement quietly. This script closes the two ways of
doing that.

1. **Pragmas.** Every ``# pragma: no cover`` and ``# pragma: no branch`` under
   ``custom_components/`` needs a justification on the same line:

       if TYPE_GUARD:  # pragma: no cover - only evaluated by the type checker

   The reason follows `` - `` and has at least three words. A pragma without a
   reason fails. Every run lists all pragmas with file, line and reason, so a
   reviewer sees them at a glance and can judge the reasons.

2. **Configuration.** The coverage settings in ``pyproject.toml`` that decide
   what is measured must be exactly the expected set below: the measured
   source, branch measurement on, no ``omit``, no ``exclude_lines``, no
   ``partial_branches``, and ``exclude_also`` with the one documented entry.
   Another coverage configuration file, which would replace ``pyproject.toml``,
   must not exist. To change the set, change ``EXPECTED`` here in the same
   pull request, where the reviewer sees it.

Run it from anywhere: ``python scripts/check_coverage_exclusions.py``. It needs
only the standard library.
"""

import io
import re
import sys
import tokenize
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCANNED_FOLDER = "custom_components"
MINIMUM_REASON_WORDS = 3
_ABSENT = None
# Section and key of pyproject.toml -> the only accepted value.
EXPECTED: dict[tuple[str, str], Any] = {
    ("run", "source"): ["custom_components/roller_shutter_suite"],
    ("run", "branch"): True,
    ("run", "omit"): _ABSENT,
    ("run", "include"): _ABSENT,
    ("report", "omit"): _ABSENT,
    ("report", "include"): _ABSENT,
    ("report", "exclude_lines"): _ABSENT,
    ("report", "partial_branches"): _ABSENT,
    ("report", "partial_also"): _ABSENT,
    # Imports for the type checker never run; nothing else is excluded.
    ("report", "exclude_also"): ["if TYPE_CHECKING:"],
}
# coverage.py prefers these files over pyproject.toml, or reads them as well.
_OTHER_CONFIGURATION_FILES = (".coveragerc", "setup.cfg", "tox.ini")
_PRAGMA = re.compile(
    r"#\s*pragma\s*:\s*no\s+(cover|branch)\b(?P<rest>.*)", re.IGNORECASE
)
_REASON = re.compile(r"\s+-\s+(?P<reason>\S.*)")


@dataclass(frozen=True)
class Pragma:
    """One exclusion pragma in the code."""

    path: str
    line: int
    kind: str
    reason: str | None

    def __str__(self) -> str:
        """Render as ``path:line: pragma - reason``."""
        reason = self.reason or "NO REASON GIVEN"
        return f"{self.path}:{self.line}: pragma: no {self.kind} - {reason}"


def find_pragmas(source: str, path: str) -> list[Pragma]:
    """Return the pragmas in the comments of one Python file."""
    found: list[Pragma] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.COMMENT:
            continue
        if match := _PRAGMA.search(token.string):
            reason = _REASON.fullmatch(match["rest"])
            text = reason["reason"].strip() if reason else None
            if text is not None and len(text.split()) < MINIMUM_REASON_WORDS:
                text = None
            found.append(Pragma(path, token.start[0], match[1].lower(), text))
    return found


def pragmas_in_tree(root: Path) -> list[Pragma]:
    """Return the pragmas of every Python file of the integration."""
    found: list[Pragma] = []
    for file in sorted((root / SCANNED_FOLDER).rglob("*.py")):
        found += find_pragmas(
            file.read_text(encoding="utf-8"), file.relative_to(root).as_posix()
        )
    return found


def configuration_problems(pyproject: str) -> list[str]:
    """Compare the coverage sections of a ``pyproject.toml`` with ``EXPECTED``."""
    coverage = tomllib.loads(pyproject).get("tool", {}).get("coverage", {})
    problems: list[str] = []
    for (section, key), expected in EXPECTED.items():
        actual = coverage.get(section, {}).get(key, _ABSENT)
        if actual != expected:
            wanted = "absent" if expected is _ABSENT else repr(expected)
            problems.append(
                f"[tool.coverage.{section}] {key} must be {wanted}, found {actual!r}"
            )
    return problems


def other_configuration_files(root: Path) -> list[str]:
    """Return coverage configuration files that would compete with pyproject.toml."""
    found: list[str] = []
    for name in _OTHER_CONFIGURATION_FILES:
        file = root / name
        if (name == ".coveragerc" and file.exists()) or (
            file.exists() and "[coverage:" in file.read_text(encoding="utf-8")
        ):
            found.append(name)
    return found


def main() -> int:
    """Run the guard on this repository."""
    pragmas = pragmas_in_tree(REPOSITORY_ROOT)
    problems = configuration_problems(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    problems += [
        f"{name} configures coverage; only pyproject.toml may"
        for name in other_configuration_files(REPOSITORY_ROOT)
    ]
    unjustified = [pragma for pragma in pragmas if pragma.reason is None]
    sys.stdout.write(f"coverage exclusions: {len(pragmas)} pragma(s) in the code\n")
    for pragma in pragmas:
        sys.stdout.write(f"  {pragma}\n")
    for problem in problems:
        sys.stdout.write(f"coverage exclusions: {problem}\n")
    if unjustified:
        sys.stdout.write(
            f"coverage exclusions: {len(unjustified)} pragma(s) without a reason. "
            "Write '# pragma: no cover - <why this cannot be tested>'\n"
        )
    if problems or unjustified:
        return 1
    sys.stdout.write("coverage exclusions: ok\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
