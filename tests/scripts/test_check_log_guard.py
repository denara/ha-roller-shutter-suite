"""The guard of the log guard finds every known way of weakening it.

The examples are source code in strings. The guard reads syntax trees, so this
file does not trip it. A decorator is joined to the line before it with ``+``,
because a line break followed by a decorator reads like an e-mail address
to the instance data guard.
"""

from pathlib import Path

import pytest

from scripts.check_log_guard import (
    FILTER_INSTALLER,
    LOG_GUARD_FILE,
    LOG_GUARD_SELF_TEST,
    check_pyproject,
    check_pytest_ini,
    check_python_source,
    check_tree,
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


def test_configuration_file_that_would_override_the_project_is_found(
    tmp_path: Path,
) -> None:
    """A ``pytest.ini`` in the root would silently replace pyproject.toml."""
    (tmp_path / "pyproject.toml").write_text(
        PYPROJECT.format(addopts="[]", filters='["error"]'), encoding="utf-8"
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    for folder in ("custom_components", "tests"):
        (tmp_path / folder).mkdir()

    findings = check_tree(tmp_path)

    assert [finding.path for finding in findings] == ["pytest.ini"]


def test_this_repository_passes() -> None:
    """Nothing in this repository weakens the log guard."""
    assert check_tree(Path(__file__).parents[2]) == []
