"""The two pytest configurations stay consistent.

A run of ``tests/core`` alone uses ``tests/core/pytest.ini``; every other run
uses ``pyproject.toml``. The settings that both share must not drift apart, and
the core file must keep the Home Assistant test plugin switched off, because
the purity proof in ``conftest.py`` depends on it.
"""

import configparser
import shlex
import tomllib
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).parents[2]
PLUGIN_SWITCH = ["-p", "no:homeassistant"]


def _project_options() -> dict[str, Any]:
    content = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    options: dict[str, Any] = content["tool"]["pytest"]["ini_options"]
    return options


def _core_options() -> configparser.SectionProxy:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(Path(__file__).with_name("pytest.ini").read_text("utf-8"))
    return parser["pytest"]


def _core_addopts() -> list[str]:
    return shlex.split(_core_options()["addopts"])


def _without_plugin_switch(arguments: list[str]) -> list[str]:
    for index in range(len(arguments) - 1):
        if arguments[index : index + 2] == PLUGIN_SWITCH:
            return arguments[:index] + arguments[index + 2 :]
    return arguments


def test_core_configuration_switches_the_home_assistant_plugin_off() -> None:
    """Without the switch the plugin imports Home Assistant before any test."""
    arguments = _core_addopts()

    assert _without_plugin_switch(arguments) != arguments, (
        "tests/core/pytest.ini must contain '-p no:homeassistant' in addopts"
    )


def test_asyncio_mode_is_the_same() -> None:
    """Both configurations run async tests the same way."""
    assert _core_options()["asyncio_mode"] == _project_options()["asyncio_mode"]


def test_filterwarnings_are_the_same() -> None:
    """Warnings are errors in both, with the same exceptions in the same order."""
    core_filters = [
        line.strip()
        for line in _core_options()["filterwarnings"].splitlines()
        if line.strip()
    ]

    assert core_filters == _project_options()["filterwarnings"]


def test_shared_command_line_options_are_the_same() -> None:
    """Apart from the plugin switch, both configurations add the same options."""
    assert _without_plugin_switch(_core_addopts()) == _project_options()["addopts"]
