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
  integration's ``__init__.py``.

The stand-in does not prove that the core imports nothing from the rest of the
integration: a plain Python module next to the core, such as ``const.py``, is
found through the stand-in and imports without a trace. That half of the purity
rule is enforced by the static import guard of block T03, not here.

In a run that also contains ``tests/ha`` the plugin is loaded and
``homeassistant`` is imported before the first test. Nothing can be proven then,
and this file stays passive; the core tests simply run along. The report header
(or, when this file is loaded too late for the header, the summary at the end)
says whether the proof was active or passive. A run that uses ``pytest.ini``
next to this file is meant to be the proof; if ``homeassistant`` is already
imported when such a run starts, the session is refused instead of going
passive.

A run with ``pytest.ini`` next to this file does not load ``tests/conftest.py``,
because pytest looks for ``conftest.py`` files only from the folder of the
active configuration file downwards. That file installs the filters for the
approved foreign warnings (``tests/foreign_warnings.toml``), so this file calls
it for such a run.
"""

import sys
from collections.abc import Iterator
from importlib.machinery import ModuleSpec
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

_FORBIDDEN = "homeassistant"
_INTEGRATION = "custom_components.roller_shutter_suite"
_INTEGRATION_DIR = (
    Path(__file__).parents[2] / "custom_components" / "roller_shutter_suite"
)
_CORE_CONFIG_FILE = Path(__file__).with_name("pytest.ini")
_SHARED_CONFTEST = Path(__file__).parents[1] / "conftest.py"
_PROOF_ACTIVE = pytest.StashKey[bool]()
_STATUS_SHOWN = pytest.StashKey[bool]()


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


def _install_stand_in() -> None:
    """Register an empty package under the integration's name.

    It has a real module spec with the integration folder as its search
    location, like a namespace package, so ``importlib`` and tools that inspect
    modules treat it as a package. It has no ``__file__`` because no file is
    executed for it.
    """
    spec = ModuleSpec(_INTEGRATION, loader=None, is_package=True)
    spec.submodule_search_locations = [str(_INTEGRATION_DIR)]
    sys.modules[_INTEGRATION] = module_from_spec(spec)


def _status_line(config: pytest.Config) -> str:
    if config.stash[_PROOF_ACTIVE]:
        return "core purity proof: active (no homeassistant module may be imported)"
    return (
        "core purity proof: passive (homeassistant was imported before the core "
        "tests; run tests/core alone for the proof)"
    )


def _core_configuration_is_active(config: pytest.Config) -> bool:
    """Tell whether ``pytest.ini`` next to this file configures the run.

    Both paths are resolved, so a checkout behind a symbolic link or a path
    written in another way is still recognized.
    """
    return (
        config.inipath is not None
        and config.inipath.resolve() == _CORE_CONFIG_FILE.resolve()
    )


def _install_foreign_warning_filters(config: pytest.Config) -> None:
    """Run the filter installation of ``tests/conftest.py``."""
    spec = spec_from_file_location("tests_shared_conftest", _SHARED_CONFTEST)
    if spec is None or spec.loader is None:
        raise pytest.UsageError("tests/conftest.py cannot be loaded")
    shared = module_from_spec(spec)
    spec.loader.exec_module(shared)
    shared.install_foreign_warning_filters(config)


def pytest_configure(config: pytest.Config) -> None:
    """Activate the proof unless Home Assistant is imported already."""
    already_imported = _home_assistant_modules()
    core_run = _core_configuration_is_active(config)
    if core_run:
        _install_foreign_warning_filters(config)
    if already_imported and core_run:
        raise pytest.UsageError(
            "tests/core/pytest.ini is the active configuration, but "
            f"homeassistant is already imported ({len(already_imported)} "
            "modules). This run is meant to prove that the core tests work "
            "without Home Assistant, and it cannot. Check that the file still "
            "switches the Home Assistant test plugin off with "
            "'-p no:homeassistant'."
        )
    proof_active = not already_imported
    config.stash[_PROOF_ACTIVE] = proof_active
    config.stash[_STATUS_SHOWN] = False
    if proof_active and _INTEGRATION not in sys.modules:
        _install_stand_in()


def pytest_report_header(config: pytest.Config) -> str:
    """Say in the header of the run whether the proof is active."""
    config.stash[_STATUS_SHOWN] = True
    return _status_line(config)


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    """Say it at the end when this file was loaded too late for the header."""
    if not config.stash[_STATUS_SHOWN]:
        terminalreporter.write_line(_status_line(config))


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
