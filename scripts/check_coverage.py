"""Guard: test coverage stays above the thresholds of each part of the code.

Coverage has a threshold because of the rule "No deprecation, ever": Home
Assistant reports deprecated usage only when the code that uses it runs, so a
code path without a test is a path where a deprecation can hide.

The thresholds apply to lines and to branches separately, and to each group as
a whole:

- ``flow``: ``config_flow.py`` and every other module outside ``core/`` whose
  file name ends in ``flow.py``: 100 %.
- ``home assistant``: everything under the integration except ``core/``,
  including the flow modules: 90 %.
- ``core``: everything under ``core/``: 95 %.

The values were proposed by the orchestrator in block T03; the project owner
may change them, nobody else.

The script reads the JSON report of coverage.py:

    uv run pytest tests/core --cov --cov-report=
    uv run pytest tests/ha --cov --cov-append --cov-report=
    uv run coverage json -o coverage.json
    python scripts/check_coverage.py coverage.json

It needs only the standard library. A module of the integration that is
missing from the report counts as not covered at all, so a file that no test
imports cannot slip through.

**The guard fails closed.** "Could not check" means here, and ends with exit
status 2: no report is named on the command line; the report is missing,
unreadable, not JSON or not shaped like a report of coverage.py; the report
was written without branch measurement (branches would then count as fully
covered); the report contains no file of the integration; the integration has
no Python file where it is expected; a module of the integration cannot be
read or parsed. Exit status 1 means a value below a threshold; every run
prints how many files each group contains. Anything unforeseen inside the
script ends with status 2 as well, with the type of the error only, never its
text or a traceback, which may name a local path.
"""

import ast
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_DIR = "custom_components/roller_shutter_suite"
CORE_DIR = f"{INTEGRATION_DIR}/core"
THRESHOLDS = {"flow": 100.0, "home assistant": 90.0, "core": 95.0}
_EXPECTED_ARGUMENTS = 2
_SUMMARY_KEYS = ("num_statements", "covered_lines", "num_branches", "covered_branches")
EXIT_FINDINGS = 1
EXIT_CANNOT_CHECK = 2

Report = dict[str, dict[str, dict[str, dict[str, int]]]]


class CannotCheckError(RuntimeError):
    """The guard could not do its job. That is a failure, never a pass."""


@dataclass
class Totals:
    """Covered and existing lines and branches of a group of files."""

    files: list[str] = field(default_factory=list)
    lines: int = 0
    covered_lines: int = 0
    branches: int = 0
    covered_branches: int = 0

    def add(self, path: str, summary: dict[str, int]) -> None:
        """Add the summary of one file of a coverage report."""
        self.files.append(path)
        self.lines += summary["num_statements"]
        self.covered_lines += summary["covered_lines"]
        self.branches += summary.get("num_branches", 0)
        self.covered_branches += summary.get("covered_branches", 0)

    @property
    def line_percent(self) -> float:
        """Line coverage; a group without lines is fully covered."""
        return 100.0 * self.covered_lines / self.lines if self.lines else 100.0

    @property
    def branch_percent(self) -> float:
        """Branch coverage; a group without branches is fully covered."""
        if not self.branches:
            return 100.0
        return 100.0 * self.covered_branches / self.branches


def normalize(path: str) -> str:
    """Return a path of a report relative to the repository, with ``/``.

    coverage.py writes relative paths, but an absolute one is cut down as well.
    """
    normalized = PurePosixPath(path.replace("\\", "/")).as_posix()
    start = normalized.find(f"{INTEGRATION_DIR}/")
    return normalized[start:] if start > 0 else normalized


def groups_of(path: str) -> list[str]:
    """Return the threshold groups a file of the integration belongs to."""
    normalized = normalize(path)
    if normalized.startswith(f"{CORE_DIR}/"):
        return ["core"]
    if not normalized.startswith(f"{INTEGRATION_DIR}/"):
        return []
    groups = ["home assistant"]
    if normalized.endswith("flow.py"):
        groups.append("flow")
    return groups


def collect(
    report: dict[str, dict[str, dict[str, dict[str, int]]]],
) -> dict[str, Totals]:
    """Sum up a coverage report per threshold group."""
    totals = {group: Totals() for group in THRESHOLDS}
    for path, data in report["files"].items():
        for group in groups_of(path):
            totals[group].add(normalize(path), data["summary"])
    return totals


def unmeasured_files(root: Path, totals: dict[str, Totals]) -> list[str]:
    """Return the modules of the integration that the report does not contain.

    Files without any statement (a docstring only) are left out by coverage.py
    when it skips empty files; they cannot be uncovered, so they are ignored.
    """
    measured = {path for group in totals.values() for path in group.files}
    missing: list[str] = []
    modules = sorted((root / INTEGRATION_DIR).rglob("*.py"))
    if not modules:
        raise CannotCheckError(
            f"no Python file found under {INTEGRATION_DIR}/. If the integration "
            "has moved, change INTEGRATION_DIR in this script"
        )
    for file in modules:
        relative = file.relative_to(root).as_posix()
        if relative in measured:
            continue
        try:
            has_statements = _has_statements(file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            # ValueError covers SyntaxError and UnicodeDecodeError.
            raise CannotCheckError(
                f"{relative} cannot be read as Python ({type(error).__name__})"
            ) from error
        if has_statements:
            missing.append(relative)
    return missing


def load_report(path: Path) -> Report:
    """Read a JSON report of coverage.py and refuse what cannot be judged."""
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        # ValueError covers a file that is not JSON or not UTF-8.
        raise CannotCheckError(
            f"the report cannot be read ({type(error).__name__}). Write it with "
            "'coverage json -o coverage.json' after the test runs with --cov"
        ) from error
    files = report.get("files") if isinstance(report, dict) else None
    if not isinstance(files, dict):
        raise CannotCheckError("the file is not a JSON report of coverage.py")
    meta = report.get("meta")
    if not isinstance(meta, dict):
        raise CannotCheckError(
            "the report has no 'meta' object, so it is not a report of coverage.py"
        )
    if meta.get("branch_coverage") is not True:
        raise CannotCheckError(
            "the report was written without branch measurement, so branches "
            "cannot be judged. The coverage configuration needs 'branch = true'"
        )
    measured = [name for name in files if groups_of(name)]
    if not measured:
        raise CannotCheckError(
            f"the report contains no file under {INTEGRATION_DIR}/. Run the tests "
            "with --cov from the root of the repository before writing it"
        )
    for name in measured:
        data = files[name]
        summary = data.get("summary") if isinstance(data, dict) else None
        if not isinstance(summary, dict) or not all(
            isinstance(summary.get(key), int) for key in _SUMMARY_KEYS
        ):
            raise CannotCheckError(
                f"the report has no complete summary for {normalize(name)}"
            )
    checked: Report = report
    return checked


def _has_statements(source: str) -> bool:
    body = ast.parse(source).body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
    ):
        body = body[1:]
    return bool(body)


def problems(totals: dict[str, Totals], missing: list[str]) -> list[str]:
    """Return every violated threshold in words."""
    found = [f"{path} is not in the coverage report at all" for path in missing]
    for group, threshold in THRESHOLDS.items():
        for kind, percent in (
            ("line", totals[group].line_percent),
            ("branch", totals[group].branch_percent),
        ):
            if percent < threshold:
                found.append(
                    f"{group}: {kind} coverage is {percent:.1f} %, "
                    f"required are {threshold:.0f} %"
                )
    return found


def main(arguments: list[str], root: Path = REPOSITORY_ROOT) -> int:
    """Check the JSON coverage report named on the command line."""
    if len(arguments) != _EXPECTED_ARGUMENTS:
        sys.stdout.write(
            "coverage: CANNOT CHECK, so this is a failure: no report was named. "
            "usage: check_coverage.py <coverage.json>\n"
        )
        return EXIT_CANNOT_CHECK
    try:
        totals = collect(load_report(Path(arguments[1])))
        missing = unmeasured_files(root, totals)
    except CannotCheckError as error:
        sys.stdout.write(f"coverage: CANNOT CHECK, so this is a failure: {error}\n")
        return EXIT_CANNOT_CHECK
    for group, threshold in THRESHOLDS.items():
        sys.stdout.write(
            f"coverage of {group}: lines {totals[group].line_percent:.1f} %, "
            f"branches {totals[group].branch_percent:.1f} % "
            f"(required {threshold:.0f} %, {len(totals[group].files)} files)\n"
        )
    found = problems(totals, missing)
    for problem in found:
        sys.stdout.write(f"coverage: {problem}\n")
    return EXIT_FINDINGS if found else 0


def run(entry: Callable[[], int]) -> int:
    """Run ``entry``; an error nobody foresaw is a failure too, never a pass.

    Only the type of the error is printed. Its text and a traceback may name
    local paths, and the output of this script may be pasted in public.
    """
    try:
        return entry()
    except Exception as error:  # noqa: BLE001 - the net for every unforeseen error
        sys.stdout.write(
            "coverage: CANNOT CHECK, so this is a failure: internal error in "
            f"check_coverage.py ({type(error).__name__})\n"
        )
        return EXIT_CANNOT_CHECK


if __name__ == "__main__":
    sys.exit(run(lambda: main(sys.argv)))
