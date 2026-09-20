"""Every script ends an unforeseen error as a failure, without its text.

A traceback has a non-zero status too, but it names the local path of the
script, and its message may name anything. Each script therefore runs its
``main`` through ``run``, which prints the type of the error and nothing else.
"""

import ast
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


# Calls that may run while a script is imported: they build constants from
# literals and touch neither the file system nor anything that can fail at
# runtime. ``dataclass`` and ``field`` belong to class definitions.
PURE_CALLS = {
    "Path",
    "Path(__file__).with_name",
    "re.compile",
    "frozenset",
    "dataclass",
    "field",
}


def _import_time_calls(node: ast.AST) -> list[str]:
    """Return the calls a top-level statement makes when the module is imported."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        arguments = node.args
        evaluated: list[ast.AST] = [
            *node.decorator_list,
            *arguments.defaults,
            *(default for default in arguments.kw_defaults if default is not None),
        ]
    elif isinstance(node, ast.ClassDef):
        evaluated = [*node.decorator_list, *node.bases]
        calls = [call for inner in node.body for call in _import_time_calls(inner)]
        return calls + [call for part in evaluated for call in _import_time_calls(part)]
    else:
        evaluated = [node]
    return [
        ast.unparse(found.func)
        for part in evaluated
        for found in ast.walk(part)
        if isinstance(found, ast.Call)
    ]


@pytest.mark.parametrize("script", sorted(RUNNERS))
def test_nothing_happens_at_import_that_the_net_could_miss(script: str) -> None:
    """Imports of the standard library, constants, definitions, and the start.

    The net begins inside ``run``. Whatever a module does while it is imported
    happens before that, so it must not be able to fail: no file is read, no
    program is started, nothing is resolved. This test reads the syntax tree,
    so a later edit cannot move work to the module level unnoticed.
    """
    tree = ast.parse((SCRIPTS_FOLDER / script).read_text(encoding="utf-8"))
    docstring, *body, start = tree.body

    assert isinstance(docstring, ast.Expr)
    assert isinstance(docstring.value, ast.Constant)
    for node in body:
        assert isinstance(
            node,
            (
                ast.Import,
                ast.ImportFrom,
                ast.Assign,
                ast.AnnAssign,
                ast.FunctionDef,
                ast.ClassDef,
            ),
        ), f"line {node.lineno}: {type(node).__name__} at module level"
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            modules = [node.module or ""]
        else:
            modules = []
        for module in modules:
            assert module.split(".")[0] in sys.stdlib_module_names, module
        assert set(_import_time_calls(node)) <= PURE_CALLS, f"line {node.lineno}"
    assert ast.unparse(start).startswith(
        "if __name__ == '__main__':\n    sys.exit(run("
    )
    assert isinstance(start, ast.If)
    assert len(start.body) == 1
    assert start.orelse == []
