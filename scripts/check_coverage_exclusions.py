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

**The guard fails closed.** "Could not check" means here, and ends with exit
status 2: ``pyproject.toml`` is missing, unreadable or not valid TOML; the
scanned folder holds no Python file; a Python file cannot be read or split into
tokens; a competing configuration file exists but cannot be read. Exit status 1
means an unjustified pragma or a changed configuration; every run says how many
files were searched.

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
PROJECT_FILE = "pyproject.toml"
EXIT_FINDINGS = 1
EXIT_CANNOT_CHECK = 2


class CannotCheckError(RuntimeError):
    """The guard could not do its job. That is a failure, never a pass."""


def _read(file: Path, relative: str) -> str:
    try:
        return file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise CannotCheckError(
            f"{relative} cannot be read ({type(error).__name__})"
        ) from error


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
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError) as error:
        raise CannotCheckError(
            f"{path} cannot be split into tokens ({type(error).__name__}); fix the "
            "file, its comments cannot be found like this"
        ) from error
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        if match := _PRAGMA.search(token.string):
            reason = _REASON.fullmatch(match["rest"])
            text = reason["reason"].strip() if reason else None
            if text is not None and len(text.split()) < MINIMUM_REASON_WORDS:
                text = None
            found.append(Pragma(path, token.start[0], match[1].lower(), text))
    return found


def scanned_files(root: Path) -> list[Path]:
    """Return the Python files of the integration; there has to be one."""
    files = sorted((root / SCANNED_FOLDER).rglob("*.py"))
    if not files:
        raise CannotCheckError(
            f"no Python file found under {SCANNED_FOLDER}/. If the folder has "
            "moved, change SCANNED_FOLDER in this script"
        )
    return files


def pragmas_in_tree(root: Path) -> list[Pragma]:
    """Return the pragmas of every Python file of the integration."""
    found: list[Pragma] = []
    for file in scanned_files(root):
        relative = file.relative_to(root).as_posix()
        found += find_pragmas(_read(file, relative), relative)
    return found


def configuration_problems(pyproject: str) -> list[str]:
    """Compare the coverage sections of a ``pyproject.toml`` with ``EXPECTED``."""
    try:
        content = tomllib.loads(pyproject)
    except tomllib.TOMLDecodeError as error:
        raise CannotCheckError(f"{PROJECT_FILE} is not valid TOML: {error}") from error
    coverage = content.get("tool", {}).get("coverage", {})
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
            file.exists() and "[coverage:" in _read(file, name)
        ):
            found.append(name)
    return found


def main(root: Path = REPOSITORY_ROOT) -> int:
    """Run the guard on this repository."""
    try:
        searched = len(scanned_files(root))
        pragmas = pragmas_in_tree(root)
        problems = configuration_problems(_read(root / PROJECT_FILE, PROJECT_FILE))
        problems += [
            f"{name} configures coverage; only pyproject.toml may"
            for name in other_configuration_files(root)
        ]
    except CannotCheckError as error:
        sys.stdout.write(
            f"coverage exclusions: CANNOT CHECK, so this is a failure: {error}\n"
        )
        return EXIT_CANNOT_CHECK
    unjustified = [pragma for pragma in pragmas if pragma.reason is None]
    sys.stdout.write(
        f"coverage exclusions: {len(pragmas)} pragma(s) in the {searched} "
        f"Python file(s) under {SCANNED_FOLDER}/\n"
    )
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
        return EXIT_FINDINGS
    sys.stdout.write("coverage exclusions: ok\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
