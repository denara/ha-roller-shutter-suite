"""Proof that the tests of the domain core run without Home Assistant.

The domain core is plain Python (guardrail 4 of the project brief). A run that
contains only ``tests/core`` must therefore finish without any ``homeassistant``
module in ``sys.modules``. This file fails every test, and the session, when
that is not the case.

Two things make the proof possible:

- ``pytest.ini`` next to this file switches the Home Assistant test plugin off,
  because the plugin itself imports ``homeassistant`` when pytest starts.
- Importing ``custom_components.roller_shutter_suite.core`` normally executes
  ``custom_components/roller_shutter_suite/__init__.py`` first, and that file
  belongs to the Home Assistant layer and imports ``homeassistant``. For a core
  run, this file registers an empty stand-in for the integration package, so
  Python finds the ``core`` package through it without executing the
  integration's ``__init__.py``. The core imports nothing from the rest of the
  integration, so it cannot notice the difference.

In a run that also contains ``tests/ha`` the plugin is loaded and
``homeassistant`` is imported before the first test. Nothing can be proven then,
and this file stays passive; the core tests simply run along.
"""

import sys
import types
from collections.abc import Iterator
from pathlib import Path

import pytest

_FORBIDDEN = "homeassistant"
_HA_PLUGIN = "homeassistant"
_INTEGRATION = "custom_components.roller_shutter_suite"
_INTEGRATION_DIR = (
    Path(__file__).parents[2] / "custom_components" / "roller_shutter_suite"
)
_PROOF_ACTIVE = pytest.StashKey[bool]()


def _home_assistant_modules() -> list[str]:
    """Return the names of all imported Home Assistant modules."""
    return sorted(
        name
        for name in sys.modules
        if name == _FORBIDDEN or name.startswith(f"{_FORBIDDEN}.")
    )


def _failure_message(modules: list[str]) -> str:
    shown = ", ".join(modules[:5])
    return (
        f"The core tests imported Home Assistant ({len(modules)} modules, for "
        f"example {shown}). Everything under tests/core and under the core "
        "package must work without Home Assistant."
    )


def pytest_configure(config: pytest.Config) -> None:
    """Activate the proof when the Home Assistant test plugin is switched off."""
    proof_active = not config.pluginmanager.has_plugin(_HA_PLUGIN)
    config.stash[_PROOF_ACTIVE] = proof_active
    if proof_active and _INTEGRATION not in sys.modules:
        stand_in = types.ModuleType(_INTEGRATION)
        stand_in.__path__ = [str(_INTEGRATION_DIR)]
        sys.modules[_INTEGRATION] = stand_in


@pytest.fixture(autouse=True)
def fail_when_home_assistant_is_imported(
    request: pytest.FixtureRequest,
) -> Iterator[None]:
    """Fail the test that runs while Home Assistant modules are imported."""
    proof_active = request.config.stash[_PROOF_ACTIVE]
    if proof_active and (modules := _home_assistant_modules()):
        # Imported before this test: by a test module during collection or by
        # an earlier test.
        pytest.fail(_failure_message(modules), pytrace=False)
    yield
    if proof_active and (modules := _home_assistant_modules()):
        pytest.fail(_failure_message(modules), pytrace=False)


def pytest_sessionfinish(session: pytest.Session) -> None:
    """Fail the session even if no test was there to notice the import."""
    if not session.config.stash[_PROOF_ACTIVE]:
        return
    if (modules := _home_assistant_modules()) and session.exitstatus == 0:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(_failure_message(modules), red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
