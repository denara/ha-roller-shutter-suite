"""The guard of the log guard finds every known way of weakening it.

The examples are source code in strings. The guard reads syntax trees, so this
file does not trip it. A decorator is joined to the line before it with ``+``,
because a line break followed by a decorator reads like an e-mail address
to the instance data guard.
"""

from pathlib import Path

import pytest

from scripts.check_log_guard import (
    EXIT_CANNOT_CHECK,
    FILTER_INSTALLER,
    GUARD_FIXTURES,
    LOG_GUARD_FILE,
    LOG_GUARD_SELF_TEST,
    CannotCheckError,
    check_pyproject,
    check_pytest_ini,
    check_python_source,
    check_tree,
    check_workflow,
    forbidden_options,
    main,
)

OTHER_TEST = "tests/ha/test_example.py"


@pytest.mark.parametrize(
    "source",
    [
        "def test_x(hass, integration_reports):\n    pass",
        "async def test_x(*, integration_reports=None):\n    pass",
        "def test_x(request):\n    request.getfixturevalue('integration_reports')",
        "import pytest\n" + "@pytest.mark.usefixtures('integration_reports')\n"
        "def test_x():\n    pass",
        "from tests.ha.conftest import integration_reports",
        "def test_x(log_guard_collector):\n    pass",
        "from tests.ha.conftest import log_guard_blind_spots",
    ],
)
def test_reports_fixture_outside_the_self_test_is_found(source: str) -> None:
    """No other test may get hold of the collected reports."""
    assert len(check_python_source(source, OTHER_TEST)) == 1
    assert check_python_source(source, LOG_GUARD_SELF_TEST) == []


@pytest.mark.parametrize(
    "source",
    [
        "def fixture(collector):\n    collector.reports.clear()",
        "def fixture(reports):\n    reports.pop()",
        "def fixture(reports):\n    del reports[:]",
    ],
)
def test_log_guard_that_drops_reports_is_found(source: str) -> None:
    """The log guard's own file must not empty what it collected."""
    assert len(check_python_source(source, LOG_GUARD_FILE)) == 1


@pytest.mark.parametrize(
    "source",
    [
        "import pytest\n"
        + "@pytest.mark.filterwarnings('ignore')\ndef test_x():\n    pass",
        "import warnings\nwarnings.simplefilter('ignore')",
        "import warnings\nwarnings.filterwarnings('ignore', category=Warning)",
        "import warnings\nwith warnings.catch_warnings():\n    pass",
        "import warnings\nwarnings.resetwarnings()",
        "from warnings import catch_warnings",
        "from warnings import simplefilter as quiet",
        "def pytest_configure(config):\n"
        "    config.addinivalue_line('filterwarnings', 'ignore')",
        "KEY = ' filterwarnings '",
    ],
)
@pytest.mark.parametrize(
    "path", [OTHER_TEST, "custom_components/roller_shutter_suite/sensor.py"]
)
def test_warning_filter_is_found(source: str, path: str) -> None:
    """Tests and integration alike may not touch the warning filters."""
    assert len(check_python_source(source, path)) == 1


@pytest.mark.parametrize(
    "name",
    # Taken from the script: written out here, each name would count as a use
    # of the fixture in this file.
    sorted(GUARD_FIXTURES),
)
@pytest.mark.parametrize(
    "path", [OTHER_TEST, "tests/ha/flows/conftest.py", LOG_GUARD_SELF_TEST]
)
def test_redefined_guard_fixture_is_found(name: str, path: str) -> None:
    """A function of the same name further down would replace the guard."""
    source = (
        "import pytest\n\n\nclass TestX:\n    @pytest.fixture(autouse=True)\n"
        f"    def {name}(self):\n        yield\n"
    )

    findings = check_python_source(source, path)

    assert any("would replace the guard" in finding.message for finding in findings)
    assert check_python_source(source, LOG_GUARD_FILE) == []


@pytest.mark.parametrize("name", sorted(GUARD_FIXTURES))
def test_guard_fixture_registered_under_its_name_by_the_decorator_is_found(
    name: str,
) -> None:
    """``name=`` of the fixture decorator registers the fixture like a definition."""
    source = (
        "import pytest\n\n\n"
        f'@pytest.fixture(name="{name}", autouse=True)\n'
        "def _other_name():\n    yield\n"
    )

    findings = check_python_source(source, OTHER_TEST)

    assert [f.message for f in findings if "would replace the guard" in f.message]
    assert check_python_source(source, LOG_GUARD_FILE) == []
    # The same string anywhere else is not a registration (two of the names
    # are handles on the reports and are refused as such, which is another rule).
    elsewhere = check_python_source(f'TEXT = "{name}"\nf(other="{name}")', OTHER_TEST)
    assert [f for f in elsewhere if "would replace the guard" in f.message] == []


@pytest.mark.parametrize(
    "source",
    [
        "import pytest\n\ndef test_x():\n    with pytest.warns(DeprecationWarning):\n"
        "        pass",
        "import pytest\n\ndef test_x():\n    with pytest.deprecated_call():\n"
        "        pass",
        "from pytest import warns",
        "from pytest import deprecated_call as quiet",
        "def test_x(recwarn):\n    pass",
    ],
)
def test_pytest_spelling_of_catching_warnings_is_found(source: str) -> None:
    """``pytest.warns`` and friends swallow a warning just like the module does."""
    assert len(check_python_source(source, OTHER_TEST)) == 1
    assert check_python_source(source, LOG_GUARD_SELF_TEST) == []


def test_only_the_installer_may_name_the_filter_option() -> None:
    """``tests/conftest.py`` installs the approved list and nothing else does."""
    source = "def f(config):\n    config.addinivalue_line('filterwarnings', 'x')"

    assert check_python_source(source, FILTER_INSTALLER) == []
    assert len(check_python_source(source, "tests/ha/conftest.py")) == 1


@pytest.mark.parametrize(
    "source",
    [
        "# integration_reports and warnings.simplefilter are only mentioned\n"
        "TEXT = 'see warnings.catch_warnings and the fixture integration_reports'",
        "import warnings\nwarnings.warn('something', stacklevel=2)",
        "import pytest\n"
        + "@pytest.mark.parametrize('x', [1])\ndef test_x(x):\n    pass",
        "reports = []\nreports.append('x')",
    ],
)
def test_harmless_source_passes(source: str) -> None:
    """Comments, prose and ordinary code do not count."""
    assert check_python_source(source, OTHER_TEST) == []


PYPROJECT = (
    "[tool.pytest.ini_options]\naddopts = {addopts}\nfilterwarnings = {filters}\n"
)
PYTEST_INI = "[pytest]\naddopts = {addopts}\nfilterwarnings =\n{filters}\n"


def test_exact_configuration_passes() -> None:
    """Only the single entry that turns warnings into errors is accepted."""
    project = PYPROJECT.format(addopts='["--strict-markers"]', filters='["error"]')
    ini = PYTEST_INI.format(addopts="-p no:homeassistant", filters="    error")

    assert check_pyproject(project, "pyproject.toml") == []
    assert check_pytest_ini(ini, "pytest.ini") == []


@pytest.mark.parametrize(
    ("addopts", "filters"),
    [
        ("[]", '["error", "ignore::DeprecationWarning"]'),
        ("[]", '["default"]'),
        ("[]", "[]"),
        ('["-W", "ignore"]', '["error"]'),
        ('["-Wignore::DeprecationWarning"]', '["error"]'),
        ('["-p", "no:warnings"]', '["error"]'),
        ('["--disable-warnings"]', '["error"]'),
        ('["-pno:warnings"]', '["error"]'),
        ('["-p", "no:logging"]', '["error"]'),
        ('["-o", "filterwarnings=ignore"]', '["error"]'),
        ('["--override-ini=filterwarnings=ignore"]', '["error"]'),
        ('["-c", "other.ini"]', '["error"]'),
    ],
)
def test_weakened_project_configuration_is_found(addopts: str, filters: str) -> None:
    """Additional filters and warning options in pyproject.toml fail."""
    text = PYPROJECT.format(addopts=addopts, filters=filters)

    assert len(check_pyproject(text, "pyproject.toml")) == 1


def test_project_configuration_without_the_setting_is_found() -> None:
    """Dropping the setting is as bad as changing it."""
    assert len(check_pyproject("[tool.pytest.ini_options]\n", "pyproject.toml")) == 1


@pytest.mark.parametrize(
    ("addopts", "filters"),
    [
        ("", "    error\n    ignore::DeprecationWarning"),
        ("", "    ignore"),
        ("-W ignore", "    error"),
        ("-p no:warnings", "    error"),
    ],
)
def test_weakened_ini_configuration_is_found(addopts: str, filters: str) -> None:
    """The same holds for the small configuration files."""
    text = PYTEST_INI.format(addopts=addopts, filters=filters)

    assert len(check_pytest_ini(text, "tests/core/pytest.ini")) == 1


def test_ordinary_options_pass() -> None:
    """Options that have nothing to do with warnings are left alone."""
    arguments = ["-p", "no:homeassistant", "--cov", "--cov-report=", "-q", "-x"]

    assert forbidden_options(arguments) == []


@pytest.mark.parametrize(
    "line",
    [
        "        run: uv run --no-sync pytest tests/ha -W ignore",
        "        run: uv run pytest -o filterwarnings=default",
        "          uv run pytest --override-ini=filterwarnings=default tests",
        "        run: uv run pytest -pno:warnings",
        "        run: uv run pytest -p no:logging tests/ha",
        "        run: pytest --disable-warnings",
        "          PYTHONWARNINGS: ignore",
        "        run: PYTHONWARNINGS=ignore uv run pytest",
        "          PYTEST_ADDOPTS: -W ignore",
        "        run: PYTEST_ADDOPTS='-p no:warnings' uv run pytest",
        "        run: uv run pytest --noconftest tests/ha",
        "        run: uv run pytest --confcutdir=tests/ha/flows tests/ha",
        "        run: uv run pytest --rootdir=tests/ha tests/ha",
        "        run: uv run pytest --cov-config=other.toml --cov",
        # A continued line: the option stands on the line after the backslash.
        "        run: uv run --no-sync pytest tests/ha \\\n            -W ignore",
        "        run: uv run pytest \\\n          tests/ha \\\n          -pno:warnings",
    ],
)
def test_weakened_command_line_in_a_workflow_is_found(line: str) -> None:
    """The workflows run pytest, so their command lines count as well."""
    text = f"jobs:\n  tests:\n    steps:\n{line}\n"

    (finding,) = check_workflow(text, ".github/workflows/test.yml")

    assert finding.line == 4  # noqa: PLR2004 - the line of the violation


def test_ordinary_workflow_passes() -> None:
    """Coverage options and the installation of the test plugin are fine."""
    text = (
        "      - run: uv run --no-sync pytest tests/core --cov --cov-report=\n"
        "      - run: uv pip install --upgrade pytest-homeassistant-custom-component\n"
        "      - run: uv run --no-sync pytest --junitxml=report.xml  # -W in a comment\n"
        "      - run: uv run --no-sync pytest tests/core \\\n"
        "          --cov --cov-report=\n"
    )

    assert check_workflow(text, ".github/workflows/test.yml") == []


def _minimal_tree(root: Path) -> None:
    """Write the smallest tree the guard accepts as complete."""
    (root / "pyproject.toml").write_text(
        PYPROJECT.format(addopts="[]", filters='["error"]'), encoding="utf-8"
    )
    for name in (
        "custom_components/example/__init__.py",
        LOG_GUARD_FILE,
        LOG_GUARD_SELF_TEST,
        ".github/workflows/test.yml",
    ):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("", encoding="utf-8")


def test_minimal_complete_tree_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The pass says how much was read."""
    _minimal_tree(tmp_path)

    assert main(tmp_path) == 0
    assert "1 workflow(s), 3 Python file(s)" in capsys.readouterr().out


@pytest.mark.parametrize(
    "removed",
    [
        "pyproject.toml",
        LOG_GUARD_FILE,
        LOG_GUARD_SELF_TEST,
        ".github/workflows/test.yml",
        "custom_components/example/__init__.py",
    ],
)
def test_incomplete_tree_cannot_be_checked(
    tmp_path: Path, removed: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Whatever the guard has to read but cannot find is a failure, not a pass."""
    _minimal_tree(tmp_path)
    (tmp_path / removed).unlink()

    with pytest.raises(CannotCheckError):
        check_tree(tmp_path)
    assert main(tmp_path) == EXIT_CANNOT_CHECK
    assert "CANNOT CHECK" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("pyproject.toml", "= ="),
        ("pyproject.toml", "tool = 1"),
        ("pyproject.toml", "[tool]\npytest = 'x'"),
        ("tests/ha/pytest.ini", "no section\n"),
        ("tests/ha/test_broken.py", "def broken(:\n"),
    ],
)
def test_file_that_cannot_be_parsed_cannot_be_checked(
    tmp_path: Path, name: str, content: str
) -> None:
    """A file the guard cannot parse may hide anything."""
    _minimal_tree(tmp_path)
    (tmp_path / name).write_text(content, encoding="utf-8")

    assert main(tmp_path) == EXIT_CANNOT_CHECK


def test_configuration_file_that_would_override_the_project_is_found(
    tmp_path: Path,
) -> None:
    """A ``pytest.ini`` in the root would silently replace pyproject.toml."""
    _minimal_tree(tmp_path)
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

    findings = check_tree(tmp_path)

    assert [finding.path for finding in findings] == ["pytest.ini"]


def test_this_repository_passes() -> None:
    """Nothing in this repository weakens the log guard."""
    assert check_tree(Path(__file__).parents[2]) == []
