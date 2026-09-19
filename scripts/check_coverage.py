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
"""

import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_DIR = "custom_components/roller_shutter_suite"
CORE_DIR = f"{INTEGRATION_DIR}/core"
THRESHOLDS = {"flow": 100.0, "home assistant": 90.0, "core": 95.0}
_EXPECTED_ARGUMENTS = 2


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
    for file in sorted((root / INTEGRATION_DIR).rglob("*.py")):
        relative = file.relative_to(root).as_posix()
        if relative in measured:
            continue
        source = file.read_text(encoding="utf-8")
        if _has_statements(source):
            missing.append(relative)
    return missing


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


def main(arguments: list[str]) -> int:
    """Check the JSON coverage report named on the command line."""
    if len(arguments) != _EXPECTED_ARGUMENTS:
        sys.stdout.write("usage: check_coverage.py <coverage.json>\n")
        return 2
    report = json.loads(Path(arguments[1]).read_text(encoding="utf-8"))
    totals = collect(report)
    for group, threshold in THRESHOLDS.items():
        sys.stdout.write(
            f"coverage of {group}: lines {totals[group].line_percent:.1f} %, "
            f"branches {totals[group].branch_percent:.1f} % "
            f"(required {threshold:.0f} %, {len(totals[group].files)} files)\n"
        )
    found = problems(totals, unmeasured_files(REPOSITORY_ROOT, totals))
    for problem in found:
        sys.stdout.write(f"coverage: {problem}\n")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
