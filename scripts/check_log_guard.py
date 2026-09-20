"""Guard: nothing weakens the log guard or the rule "warnings are errors".

The rule behind this script is "No deprecation, ever" in ``tasks/README.md``.
The script fails when

- a file other than the log guard itself (``tests/ha/conftest.py``) and its
  self-test (``tests/ha/test_report_guard.py``) mentions the fixtures
  ``integration_reports`` or ``log_guard_collector`` or the helper
  ``log_guard_blind_spots``, which are the only handles on the collected
  reports; when any file other than the log guard defines a function with the
  name of one of the guard's fixtures, which would replace the fixture for the
  tests below it; or when the log guard's own file empties a list;
- ``filterwarnings`` in ``pyproject.toml`` or in a ``pytest.ini`` under
  ``tests/`` is anything but exactly ``error``, or ``addopts`` there carries an
  option that changes warnings, logging or the configuration (``-W``,
  ``-o``/``--override-ini``, ``-p no:warnings``, ``-p no:logging``, ...); the
  same options on a ``pytest`` command line in a workflow, and the variable
  ``PYTHONWARNINGS`` there;
- a test or the integration uses ``pytest.mark.filterwarnings``,
  ``warnings.simplefilter``, ``warnings.filterwarnings``,
  ``warnings.catch_warnings`` or ``warnings.resetwarnings``, or pytest's
  spelling of the same thing: ``pytest.warns``, ``pytest.deprecated_call`` and
  the ``recwarn`` fixture (only the self-test of the log guard may, should it
  ever need to); or the word ``filterwarnings`` appears as a string outside two
  files: ``tests/conftest.py``, which installs the filters of
  ``tests/foreign_warnings.toml`` and checks the filters in effect, and
  ``tests/core/test_pytest_configuration.py``, which compares the
  configurations.
Python files are read as syntax trees, so comments and documentation may talk
about these names. What ``tests/foreign_warnings.toml`` may contain is checked
by ``scripts/check_foreign_warnings.py``; that the filters in effect are exactly
that list is checked at runtime in every test folder
(``tests/core/test_pytest_configuration.py``, ``tests/ha/test_warning_filters.py``).

**The guard fails closed.** "Could not check" means here, and ends with exit
status 2: ``pyproject.toml`` is missing, unreadable or not valid TOML; a
``pytest.ini`` cannot be read or parsed; the log guard (``tests/ha/conftest.py``)
or its self-test does not exist, so there is nothing left to protect; the
workflow folder holds no workflow; a scanned folder holds no Python file; a
Python file cannot be read or parsed. Exit status 1 means findings; 0 means
that the files were really read, and the last line says how many of each kind.

Anything unforeseen inside the script ends with status 2 as well, with the type
of the error only, never its text or a traceback, which may name a local path.

Run it from anywhere: ``python scripts/check_log_guard.py``. It needs only the
standard library.
"""

import ast
import configparser
import os
import shlex
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ``__file__`` is absolute; nothing at module level touches the file system.
REPOSITORY_ROOT = Path(__file__).parents[1]
SCANNED_FOLDERS = ("custom_components", "tests")
LOG_GUARD_FILE = "tests/ha/conftest.py"
LOG_GUARD_SELF_TEST = "tests/ha/test_report_guard.py"
FILTER_INSTALLER = "tests/conftest.py"
FILTER_CHECK = "tests/core/test_pytest_configuration.py"
WORKFLOW_FOLDER = ".github/workflows"
REPORTS_FIXTURE = "integration_reports"
# Names that give access to what the log guard collected.
_GUARD_HANDLES = {REPORTS_FIXTURE, "log_guard_collector", "log_guard_blind_spots"}
# Fixtures of the log guard. A function of the same name in another file would
# replace the fixture for the tests below that file.
GUARD_FIXTURES = {
    REPORTS_FIXTURE,
    "log_guard_collector",
    "fail_on_logged_deprecation",
    "auto_enable_custom_integrations",
}
REQUIRED_FILTERS = ["error"]
_FILTER_KEY = "filterwarnings"
_WARNING_FUNCTIONS = {
    "simplefilter",
    "filterwarnings",
    "catch_warnings",
    "resetwarnings",
}
# pytest's own ways of catching a warning instead of failing on it.
_PYTEST_WARNING_CATCHERS = {"warns", "deprecated_call", "recwarn"}
_OPTION_PREFIXES = (
    "-W",
    "--pythonwarnings",
    "--disable-warnings",
    "-o",
    "--override-ini",
    "-c",
    "--config-file",
)
_SWITCHED_OFF_PLUGINS = ("no:warnings", "no:logging")
_WARNINGS_VARIABLE = "PYTHONWARNINGS"
_EMPTYING_METHODS = {"clear", "pop", "remove"}
_FILTER_FILES = (FILTER_INSTALLER, FILTER_CHECK)
_OVERRIDING_FILES = ("pytest.ini", ".pytest.ini", "pytest.toml", ".pytest.toml")
PROJECT_FILE = "pyproject.toml"
EXIT_FINDINGS = 1
EXIT_CANNOT_CHECK = 2


class CannotCheckError(RuntimeError):
    """The guard could not do its job. That is a failure, never a pass."""


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
    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError) as error:
        raise CannotCheckError(
            f"{path} cannot be parsed as Python ({type(error).__name__}); fix the "
            "file, it cannot be judged like this"
        ) from error
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        names = _names(node)
        is_string = isinstance(node, ast.Constant)
        if _GUARD_HANDLES & set(names) and path not in (
            LOG_GUARD_FILE,
            LOG_GUARD_SELF_TEST,
        ):
            findings.append(
                Finding(
                    path,
                    line,
                    f"only {LOG_GUARD_SELF_TEST} may use "
                    f"'{(_GUARD_HANDLES & set(names)).pop()}'; no other test may "
                    "see or clear the collected reports",
                )
            )
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.name in GUARD_FIXTURES
            and path != LOG_GUARD_FILE
        ):
            findings.append(
                Finding(
                    path,
                    line,
                    f"'{node.name}' is a fixture of the log guard; defining it "
                    f"outside {LOG_GUARD_FILE} would replace the guard",
                )
            )
        if (
            not is_string
            and set(names) & _PYTEST_WARNING_CATCHERS
            and path != LOG_GUARD_SELF_TEST
        ):
            findings.append(
                Finding(
                    path,
                    line,
                    f"'{names[0]}' catches warnings instead of failing on them; "
                    "fix the cause of the warning",
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
    findings += [
        Finding(path, 0, f"addopts must not carry the option '{option}'")
        for option in forbidden_options(addopts)
    ]
    return findings


def forbidden_options(arguments: list[str]) -> list[str]:
    """Return the pytest options that change warnings, logging or configuration.

    ``-p`` is judged together with the plugin it names, attached (``-pno:x``)
    or as the next argument.
    """
    found: list[str] = []
    for position, option in enumerate(arguments):
        follower = arguments[position + 1] if position + 1 < len(arguments) else ""
        if option.startswith("-p") and not option.startswith("--"):
            plugin = option[2:] or follower
            if plugin in _SWITCHED_OFF_PLUGINS:
                found.append(f"-p {plugin}")
        elif option.startswith(_OPTION_PREFIXES):
            found.append(option)
    return found


def check_workflow(text: str, path: str) -> list[Finding]:
    """Check the pytest command lines of one workflow file.

    The file is read line by line instead of being parsed as YAML, because the
    script uses the standard library only.
    """
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if _WARNINGS_VARIABLE in line:
            findings.append(
                Finding(path, number, f"{_WARNINGS_VARIABLE} changes warning filters")
            )
        if "pytest" not in line:
            continue
        try:
            arguments = shlex.split(line, comments=True)
        except ValueError:
            arguments = line.split()
        if "pytest" not in arguments:
            continue
        arguments = arguments[arguments.index("pytest") + 1 :]
        findings += [
            Finding(path, number, f"pytest must not be run with '{option}'")
            for option in forbidden_options(arguments)
        ]
    return findings


def check_pyproject(text: str, path: str) -> list[Finding]:
    """Check the pytest section of a ``pyproject.toml``."""
    try:
        content = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise CannotCheckError(f"{path} is not valid TOML: {error}") from error
    options = _table(content, "tool", "pytest", "ini_options")
    addopts = options.get("addopts", [])
    if isinstance(addopts, str):
        addopts = shlex.split(addopts)
    return _check_options(options.get(_FILTER_KEY), list(addopts), path)


def check_pytest_ini(text: str, path: str) -> list[Finding]:
    """Check a ``pytest.ini``."""
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(text)
    except configparser.Error as error:
        raise CannotCheckError(
            f"{path} cannot be parsed ({type(error).__name__})"
        ) from error
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
        if _exists(root / name, name)
    ]


def _exists(path: Path, shown: str) -> bool:
    """Tell whether a path exists; an error other than "not there" is not a "no".

    ``Path.exists`` and its relatives answer ``False`` for every error of the
    operating system, so a file that cannot be examined would look absent.
    """
    try:
        path.lstat()
    except FileNotFoundError, NotADirectoryError:
        return False
    except OSError as error:
        raise CannotCheckError(
            f"{shown} cannot be examined ({type(error).__name__})"
        ) from error
    return True


def _walk(folder: Path, shown: str, wanted: Callable[[str], bool]) -> list[Path]:
    """Return the wanted files below ``folder``, sorted; empty if it is not there.

    ``Path.rglob`` passes over a folder it cannot read without a word, and the
    files in it would simply not be checked. Here such a folder is a failure.
    """
    if not _exists(folder, shown):
        return []

    def refuse(error: OSError) -> None:
        raise CannotCheckError(
            f"a folder under {shown}/ cannot be listed ({type(error).__name__})"
        ) from error

    found: list[Path] = []
    for directory, _folders, names in os.walk(folder, onerror=refuse):
        found += [Path(directory) / name for name in names if wanted(name)]
    return sorted(found)


def _is_python(name: str) -> bool:
    return name.endswith(".py")


def _is_workflow(name: str) -> bool:
    return name.endswith((".yml", ".yaml"))


@dataclass(frozen=True)
class Inputs:
    """The files a run reads, by kind. Every kind except ``ini`` has to exist."""

    ini: list[Path]
    workflows: list[Path]
    python: list[Path]

    def summary(self) -> str:
        """Say how much is read."""
        return (
            f"{PROJECT_FILE}, {len(self.ini)} pytest.ini, {len(self.workflows)} "
            f"workflow(s), {len(self.python)} Python file(s)"
        )


def inputs(root: Path) -> Inputs:
    """Find what has to be read, and refuse a tree where it is not there."""
    for required in (PROJECT_FILE, LOG_GUARD_FILE, LOG_GUARD_SELF_TEST):
        if not _exists(root / required, required):
            raise CannotCheckError(
                f"{required} does not exist. If it has moved, change its path in "
                "this script; without it there is nothing to protect"
            )
    workflows = _walk(root / WORKFLOW_FOLDER, WORKFLOW_FOLDER, _is_workflow)
    if not workflows:
        raise CannotCheckError(
            f"no workflow found under {WORKFLOW_FOLDER}/, so no pytest command "
            "line of CI could be checked"
        )
    python: list[Path] = []
    for folder in SCANNED_FOLDERS:
        found = _walk(root / folder, folder, _is_python)
        if not found:
            raise CannotCheckError(
                f"no Python file found under {folder}/. If the folder has moved, "
                "change SCANNED_FOLDERS in this script"
            )
        python += found
    ini = _walk(root / "tests", "tests", lambda name: name == "pytest.ini")
    return Inputs(ini, workflows, python)


def _read(file: Path, relative: str) -> str:
    try:
        return file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise CannotCheckError(
            f"{relative} cannot be read ({type(error).__name__})"
        ) from error


def check_tree(root: Path) -> list[Finding]:
    """Check the pytest configurations and every scanned Python file."""
    found = inputs(root)
    findings = check_pyproject(_read(root / PROJECT_FILE, PROJECT_FILE), PROJECT_FILE)
    findings += _overriding_configurations(root)
    for files, check in (
        (found.ini, check_pytest_ini),
        (found.workflows, check_workflow),
        (found.python, check_python_source),
    ):
        for file in files:
            relative = file.relative_to(root).as_posix()
            findings += check(_read(file, relative), relative)
    return findings


def main(root: Path = REPOSITORY_ROOT) -> int:
    """Run the guard on this repository."""
    try:
        summary = inputs(root).summary()
        findings = check_tree(root)
    except CannotCheckError as error:
        sys.stdout.write(f"log guard: CANNOT CHECK, so this is a failure: {error}\n")
        return EXIT_CANNOT_CHECK
    for finding in findings:
        sys.stdout.write(f"{finding}\n")
    if findings:
        sys.stdout.write(f"log guard: {len(findings)} finding(s)\n")
        return EXIT_FINDINGS
    sys.stdout.write(f"log guard: ok (checked {summary})\n")
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
            "log guard: CANNOT CHECK, so this is a failure: internal error in "
            f"check_log_guard.py ({type(error).__name__})\n"
        )
        return EXIT_CANNOT_CHECK


if __name__ == "__main__":
    sys.exit(run(main))
