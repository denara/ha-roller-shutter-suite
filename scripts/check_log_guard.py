"""Guard: nothing weakens the log guard or the rule "warnings are errors".

The rule behind this script is "No deprecation, ever" in ``tasks/README.md``.
The script fails when

- a file other than the log guard itself (``tests/ha/conftest.py``) and its
  self-test (``tests/ha/test_report_guard.py``) mentions the
  ``integration_reports`` fixture, which is the only handle on the collected
  reports, or when the log guard's own file empties a list;
- ``filterwarnings`` in ``pyproject.toml`` or in a ``pytest.ini`` under ``tests/`` is anything
  but exactly ``error``, or ``addopts`` there carries a warning option;
- a test or the integration uses ``pytest.mark.filterwarnings``,
  ``warnings.simplefilter``, ``warnings.filterwarnings``,
  ``warnings.catch_warnings`` or ``warnings.resetwarnings``, or the word
  ``filterwarnings`` appears as a string outside two files: ``tests/conftest.py``,
  which installs the filters of ``tests/foreign_warnings.toml``, and
  ``tests/core/test_pytest_configuration.py``, which reads the option to check
  it.

Python files are read as syntax trees, so comments and documentation may talk
about these names. What ``tests/foreign_warnings.toml`` may contain is checked
by ``scripts/check_foreign_warnings.py``; that the filters in effect are exactly
that list is checked by ``tests/core/test_pytest_configuration.py``.

Run it from anywhere: ``python scripts/check_log_guard.py``. It needs only the
standard library.
"""

import ast
import configparser
import shlex
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCANNED_FOLDERS = ("custom_components", "tests")
LOG_GUARD_FILE = "tests/ha/conftest.py"
LOG_GUARD_SELF_TEST = "tests/ha/test_report_guard.py"
FILTER_INSTALLER = "tests/conftest.py"
FILTER_CHECK = "tests/core/test_pytest_configuration.py"
REPORTS_FIXTURE = "integration_reports"
REQUIRED_FILTERS = ["error"]
_FILTER_KEY = "filterwarnings"
_WARNING_FUNCTIONS = {
    "simplefilter",
    "filterwarnings",
    "catch_warnings",
    "resetwarnings",
}
_WARNING_OPTIONS = ("-W", "--pythonwarnings", "--disable-warnings")
_EMPTYING_METHODS = {"clear", "pop", "remove"}
_FILTER_FILES = (FILTER_INSTALLER, FILTER_CHECK)
_OVERRIDING_FILES = ("pytest.ini", ".pytest.ini", "pytest.toml", ".pytest.toml")


@dataclass(frozen=True)
class Finding:
    """One way in which the guard would be weakened."""

    path: str
    line: int
    message: str

    def __str__(self) -> str:
        """Render as ``path:line: message``."""
        return f"{self.path}:{self.line}: {self.message}"


def _names(node: ast.AST) -> list[str]:
    """Return identifiers and whole strings that a syntax node carries."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, (ast.arg, ast.keyword)):
        return [node.arg] if node.arg else []
    if isinstance(node, ast.alias):
        return [node.name.rsplit(".", 1)[-1]]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value.strip()]
    return []


def _empties_a_list(node: ast.AST) -> bool:
    if isinstance(node, ast.Delete):
        return True
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _EMPTYING_METHODS
    )


def check_python_source(source: str, path: str) -> list[Finding]:
    """Check one Python file of the tests or of the integration."""
    findings: list[Finding] = []
    for node in ast.walk(ast.parse(source, filename=path)):
        line = getattr(node, "lineno", 0)
        names = _names(node)
        is_string = isinstance(node, ast.Constant)
        if REPORTS_FIXTURE in names and path not in (
            LOG_GUARD_FILE,
            LOG_GUARD_SELF_TEST,
        ):
            findings.append(
                Finding(
                    path,
                    line,
                    f"only {LOG_GUARD_SELF_TEST} may use the fixture "
                    f"'{REPORTS_FIXTURE}'; no other test may see or clear the "
                    "collected reports",
                )
            )
        if path == LOG_GUARD_FILE and _empties_a_list(node):
            findings.append(
                Finding(path, line, "the log guard must not drop collected reports")
            )
        if is_string and _FILTER_KEY in names and path not in _FILTER_FILES:
            findings.append(
                Finding(
                    path,
                    line,
                    f"only {FILTER_INSTALLER} may install warning filters, and "
                    "only those of tests/foreign_warnings.toml",
                )
            )
        if not is_string and set(names) & _WARNING_FUNCTIONS:
            findings.append(
                Finding(
                    path,
                    line,
                    f"'{names[0]}' changes or hides warnings; the only way to "
                    "exempt a foreign warning is tests/foreign_warnings.toml",
                )
            )
    return findings


def _check_options(filters: object, addopts: list[str], path: str) -> list[Finding]:
    findings: list[Finding] = []
    if filters != REQUIRED_FILTERS:
        findings.append(
            Finding(path, 0, f"{_FILTER_KEY} must be exactly {REQUIRED_FILTERS}")
        )
    for position, option in enumerate(addopts):
        follower = addopts[position + 1] if position + 1 < len(addopts) else ""
        if option.startswith(_WARNING_OPTIONS) or (
            option == "-p" and follower == "no:warnings"
        ):
            findings.append(
                Finding(path, 0, f"addopts must not carry the option '{option}'")
            )
    return findings


def check_pyproject(text: str, path: str) -> list[Finding]:
    """Check the pytest section of a ``pyproject.toml``."""
    options = tomllib.loads(text).get("tool", {}).get("pytest", {})
    options = options.get("ini_options", {})
    addopts = options.get("addopts", [])
    if isinstance(addopts, str):
        addopts = shlex.split(addopts)
    return _check_options(options.get(_FILTER_KEY), list(addopts), path)


def check_pytest_ini(text: str, path: str) -> list[Finding]:
    """Check a ``pytest.ini``."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    options = parser["pytest"] if parser.has_section("pytest") else {}
    raw_filters = options.get(_FILTER_KEY)
    filters = (
        None
        if raw_filters is None
        else [line.strip() for line in raw_filters.splitlines() if line.strip()]
    )
    return _check_options(filters, shlex.split(options.get("addopts", "")), path)


def _overriding_configurations(root: Path) -> list[Finding]:
    """Find files in the root that pytest would prefer over pyproject.toml."""
    return [
        Finding(name, 0, "this file would replace the pytest section of pyproject.toml")
        for name in _OVERRIDING_FILES
        if (root / name).exists()
    ]


def check_tree(root: Path) -> list[Finding]:
    """Check the pytest configurations and every scanned Python file."""
    findings = check_pyproject(
        (root / "pyproject.toml").read_text(encoding="utf-8"), "pyproject.toml"
    )
    findings += _overriding_configurations(root)
    for file in sorted((root / "tests").rglob("pytest.ini")):
        findings += check_pytest_ini(
            file.read_text(encoding="utf-8"), file.relative_to(root).as_posix()
        )
    for folder in SCANNED_FOLDERS:
        for file in sorted((root / folder).rglob("*.py")):
            findings += check_python_source(
                file.read_text(encoding="utf-8"), file.relative_to(root).as_posix()
            )
    return findings


def main() -> int:
    """Run the guard on this repository."""
    findings = check_tree(REPOSITORY_ROOT)
    for finding in findings:
        sys.stdout.write(f"{finding}\n")
    if findings:
        sys.stdout.write(f"log guard: {len(findings)} finding(s)\n")
        return 1
    sys.stdout.write("log guard: ok\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
