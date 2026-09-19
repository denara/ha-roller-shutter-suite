"""The pytest configurations stay consistent.

A run of ``tests/core`` alone uses ``tests/core/pytest.ini``, a run of
``tests/scripts`` alone uses ``tests/scripts/pytest.ini``; every other run uses
``pyproject.toml``. The settings must not drift apart, and the two small files
must keep the Home Assistant test plugin switched off: the purity proof in
``conftest.py`` depends on it, and so does running on native Windows.

Every key is compared, not a chosen few: a key that exists in one file must
exist in the other with the same meaning. The only differences allowed are the
plugin switch, ``testpaths`` (meaningless for a run of one folder) and the way
``pythonpath`` is written, which has to lead to the same folder.
"""

import configparser
import shlex
import tomllib
from pathlib import Path
from typing import Any

import pytest

from scripts.check_foreign_warnings import load_entries

REPOSITORY_ROOT = Path(__file__).parents[2]
PLUGIN_SWITCH = ["-p", "no:homeassistant"]
SMALL_CONFIGURATIONS = ["tests/core/pytest.ini", "tests/scripts/pytest.ini"]
ONLY_IN_THE_PROJECT_CONFIGURATION = {"testpaths"}
# Keys that hold a list. In an ini file each line is one item.
LIST_KEYS = {"filterwarnings", "pythonpath", "testpaths"}


def _without_plugin_switch(arguments: list[str]) -> list[str]:
    for index in range(len(arguments) - 1):
        if arguments[index : index + 2] == PLUGIN_SWITCH:
            return arguments[:index] + arguments[index + 2 :]
    return arguments


def _normalized(key: str, value: Any, folder: Path) -> Any:
    """Bring a value of either file format into a comparable form."""
    if key == "addopts":
        arguments = shlex.split(value) if isinstance(value, str) else list(value)
        return _without_plugin_switch(arguments)
    if key in LIST_KEYS and isinstance(value, str):
        value = [line.strip() for line in value.splitlines() if line.strip()]
    if key == "pythonpath":
        return [(folder / entry).resolve() for entry in value]
    return value


def _project_options() -> dict[str, Any]:
    content = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    options: dict[str, Any] = content["tool"]["pytest"]["ini_options"]
    return {
        key: _normalized(key, value, REPOSITORY_ROOT)
        for key, value in options.items()
        if key not in ONLY_IN_THE_PROJECT_CONFIGURATION
    }


def _raw_small_options(configuration: str) -> dict[str, str]:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string((REPOSITORY_ROOT / configuration).read_text("utf-8"))
    return dict(parser["pytest"])


def _small_options(configuration: str) -> dict[str, Any]:
    folder = (REPOSITORY_ROOT / configuration).parent
    return {
        key: _normalized(key, value, folder)
        for key, value in _raw_small_options(configuration).items()
    }


@pytest.mark.parametrize("configuration", SMALL_CONFIGURATIONS)
def test_small_configuration_switches_the_home_assistant_plugin_off(
    configuration: str,
) -> None:
    """Without the switch the plugin imports Home Assistant before any test."""
    arguments = shlex.split(_raw_small_options(configuration)["addopts"])

    assert _without_plugin_switch(arguments) != arguments, (
        f"{configuration} must contain '-p no:homeassistant' in addopts"
    )


@pytest.mark.parametrize("configuration", SMALL_CONFIGURATIONS)
def test_every_setting_is_the_same_as_in_the_project_configuration(
    configuration: str,
) -> None:
    """No key is missing on either side, and every value means the same."""
    assert _small_options(configuration) == _project_options()


def test_normalization_keeps_real_differences_visible() -> None:
    """The comparison cannot be satisfied by a different value or a lost key."""
    folder = REPOSITORY_ROOT / "tests" / "core"

    assert _normalized("asyncio_mode", "strict", folder) != "auto"
    assert _normalized("filterwarnings", "error\nignore", folder) == [
        "error",
        "ignore",
    ]
    assert _normalized("addopts", "-p no:homeassistant -x", folder) == ["-x"]
    assert _normalized("pythonpath", "..", folder) != [REPOSITORY_ROOT]


def test_filters_in_effect_are_the_approved_list(
    pytestconfig: pytest.Config,
) -> None:
    """Warnings are errors, except the entries of ``foreign_warnings.toml``.

    This looks at the running configuration, so a filter from a command line
    option, a plugin or a ``conftest.py`` is seen as well.
    """
    expected = ["error", *(entry.as_filter() for entry in load_entries())]

    assert pytestconfig.getini("filterwarnings") == expected
    assert not pytestconfig.getoption("pythonwarnings")
