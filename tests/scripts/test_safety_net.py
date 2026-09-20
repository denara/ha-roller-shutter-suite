"""Every script ends an unforeseen error as a failure, without its text.

A traceback has a non-zero status too, but it names the local path of the
script, and its message may name anything. Each script therefore runs its
``main`` through ``run``, which prints the type of the error and nothing else.
"""

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from scripts import (
    check_core_purity,
    check_coverage,
    check_coverage_exclusions,
    check_deprecated_names,
    check_foreign_warnings,
    check_instance_data,
    check_log_guard,
    check_versions,
    summarize_test_report,
)

SCRIPTS_FOLDER = Path(__file__).parents[2] / "scripts"
RUNNERS: dict[str, Callable[[Callable[[], int]], int]] = {
    "check_core_purity.py": check_core_purity.run,
    "check_coverage.py": check_coverage.run,
    "check_coverage_exclusions.py": check_coverage_exclusions.run,
    "check_deprecated_names.py": check_deprecated_names.run,
    "check_foreign_warnings.py": check_foreign_warnings.run,
    "check_instance_data.py": check_instance_data.run,
    "check_log_guard.py": check_log_guard.run,
    "check_versions.py": check_versions.run,
    "summarize_test_report.py": summarize_test_report.run,
}
CANNOT_CHECK = 2


def test_every_script_has_the_net() -> None:
    """A new script has to be added here, and with it its ``run``."""
    assert sorted(RUNNERS) == sorted(file.name for file in SCRIPTS_FOLDER.glob("*.py"))


@pytest.mark.parametrize("script", sorted(RUNNERS))
def test_unforeseen_error_ends_with_status_two_and_its_type_only(
    script: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Never a pass, never a traceback, never the text of the error."""
    message = "text-that-must-not-appear"

    def entry() -> int:
        raise LookupError(message)

    assert RUNNERS[script](entry) == CANNOT_CHECK
    output = capsys.readouterr().out
    assert f"internal error in {script} (LookupError)" in output
    assert message not in output
    assert RUNNERS[script](lambda: 0) == 0


@pytest.mark.parametrize("script", sorted(RUNNERS))
def test_script_is_started_through_the_net(script: str) -> None:
    """The last line of every script hands ``main`` to ``run``."""
    last = (SCRIPTS_FOLDER / script).read_text(encoding="utf-8").splitlines()[-1]

    assert last.startswith("    sys.exit(run(")


def test_malformed_report_on_the_command_line_shows_no_traceback(
    tmp_path: Path,
) -> None:
    """From the outside: a report whose ``meta`` is not an object."""
    report = tmp_path / "coverage.json"
    report.write_text('{"meta": [], "files": {}}', encoding="utf-8")

    result = subprocess.run(  # noqa: S603 - this interpreter, a script of this repository
        [sys.executable, str(SCRIPTS_FOLDER / "check_coverage.py"), str(report)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == CANNOT_CHECK
    assert "CANNOT CHECK" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr
