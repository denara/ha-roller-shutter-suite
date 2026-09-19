"""Set-up for the unit tests of the guard scripts.

A run with ``pytest.ini`` next to this file does not load ``tests/conftest.py``,
because pytest looks for ``conftest.py`` files only from the folder of the
active configuration file downwards. That file installs the filters for the
approved foreign warnings (``tests/foreign_warnings.toml``), so this file calls
it for such a run. In every other run pytest has loaded it already.
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

_OWN_CONFIG_FILE = Path(__file__).with_name("pytest.ini")
_SHARED_CONFTEST = Path(__file__).parents[1] / "conftest.py"


def pytest_configure(config: pytest.Config) -> None:
    """Install the shared warning filters when this folder runs on its own."""
    if config.inipath is None or config.inipath.resolve() != _OWN_CONFIG_FILE.resolve():
        return
    spec = spec_from_file_location("tests_shared_conftest", _SHARED_CONFTEST)
    if spec is None or spec.loader is None:
        raise pytest.UsageError("tests/conftest.py cannot be loaded")
    shared = module_from_spec(spec)
    spec.loader.exec_module(shared)
    shared.install_foreign_warning_filters(config)
