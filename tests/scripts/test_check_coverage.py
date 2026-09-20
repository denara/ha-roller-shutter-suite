"""The coverage guard applies the right threshold to the right files."""

import json
from pathlib import Path

import pytest

from scripts.check_coverage import (
    INTEGRATION_DIR,
    THRESHOLDS,
    collect,
    groups_of,
    main,
    problems,
    unmeasured_files,
)

Summary = dict[str, int]
Report = dict[str, dict[str, dict[str, Summary]]]


def _summary(lines: int, covered: int, branches: int = 0, taken: int = 0) -> Summary:
    return {
        "num_statements": lines,
        "covered_lines": covered,
        "num_branches": branches,
        "covered_branches": taken,
    }


def _report(files: dict[str, Summary]) -> Report:
    return {"files": {path: {"summary": summary} for path, summary in files.items()}}


def test_thresholds_are_the_ones_of_the_block() -> None:
    """Changing a threshold is a decision of the project owner."""
    assert THRESHOLDS == {"flow": 100.0, "home assistant": 90.0, "core": 95.0}


@pytest.mark.parametrize(
    ("path", "groups"),
    [
        (f"{INTEGRATION_DIR}/config_flow.py", ["home assistant", "flow"]),
        (f"{INTEGRATION_DIR}/window_subentry_flow.py", ["home assistant", "flow"]),
        (f"{INTEGRATION_DIR}/__init__.py", ["home assistant"]),
        (f"{INTEGRATION_DIR}/core/arbiter.py", ["core"]),
        (f"{INTEGRATION_DIR}/core/flow.py", ["core"]),
        (f"checkout/{INTEGRATION_DIR}/cover.py", ["home assistant"]),
        (INTEGRATION_DIR.replace("/", "\\") + "\\core\\model.py", ["core"]),
        ("tests/ha/test_config_entry.py", []),
    ],
)
def test_file_belongs_to_its_groups(path: str, groups: list[str]) -> None:
    """Flow modules count twice, the core counts on its own."""
    assert groups_of(path) == groups


def test_fully_covered_report_passes() -> None:
    """Files without statements or branches count as covered."""
    totals = collect(
        _report(
            {
                f"{INTEGRATION_DIR}/config_flow.py": _summary(10, 10, 4, 4),
                f"{INTEGRATION_DIR}/__init__.py": _summary(20, 19),
                f"{INTEGRATION_DIR}/core/__init__.py": _summary(0, 0),
            }
        )
    )

    assert problems(totals, []) == []


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({f"{INTEGRATION_DIR}/config_flow.py": _summary(100, 99)}, "flow: line"),
        (
            {
                f"{INTEGRATION_DIR}/config_flow.py": _summary(10, 10, 4, 3),
                f"{INTEGRATION_DIR}/cover.py": _summary(10, 10, 100, 100),
            },
            "flow: branch",
        ),
        ({f"{INTEGRATION_DIR}/cover.py": _summary(100, 89)}, "home assistant: line"),
        (
            {f"{INTEGRATION_DIR}/cover.py": _summary(10, 10, 10, 8)},
            "home assistant: branch",
        ),
        ({f"{INTEGRATION_DIR}/core/arbiter.py": _summary(100, 94)}, "core: line"),
        (
            {f"{INTEGRATION_DIR}/core/arbiter.py": _summary(10, 10, 100, 94)},
            "core: branch",
        ),
    ],
)
def test_value_below_a_threshold_fails(
    files: dict[str, Summary], expected: str
) -> None:
    """Lines and branches are judged separately for every group."""
    found = problems(collect(_report(files)), [])

    assert len(found) == 1
    assert found[0].startswith(expected)


def test_value_exactly_at_the_threshold_passes() -> None:
    """The threshold itself is enough."""
    files = {
        f"{INTEGRATION_DIR}/cover.py": _summary(100, 90, 10, 9),
        f"{INTEGRATION_DIR}/core/arbiter.py": _summary(100, 95, 20, 19),
    }

    assert problems(collect(_report(files)), []) == []


def test_module_missing_from_the_report_fails(tmp_path: Path) -> None:
    """A module that no test imports cannot hide; an empty package can."""
    package = tmp_path / INTEGRATION_DIR
    (package / "core").mkdir(parents=True)
    (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (package / "cover.py").write_text('"""Docstring."""\n\nVALUE = 1\n', "utf-8")
    (package / "core" / "__init__.py").write_text('"""Only words."""\n', "utf-8")
    totals = collect(_report({f"{INTEGRATION_DIR}/__init__.py": _summary(1, 1)}))

    missing = unmeasured_files(tmp_path, totals)

    assert missing == [f"{INTEGRATION_DIR}/cover.py"]
    assert len(problems(totals, missing)) == 1


def test_command_line_reads_a_report_file(tmp_path: Path) -> None:
    """The script fails with exit code 1 on a report below the thresholds."""
    report = tmp_path / "coverage.json"
    report.write_text(
        json.dumps(_report({f"{INTEGRATION_DIR}/config_flow.py": _summary(2, 1)})),
        encoding="utf-8",
    )

    assert main(["check_coverage.py", str(report)]) == 1
    assert main(["check_coverage.py"]) == 2  # noqa: PLR2004 - usage error
