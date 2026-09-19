"""Warning filters for every test folder: the list of foreign warnings.

The pytest configuration turns every warning into an error. The only
exemptions are the entries of ``tests/foreign_warnings.toml``, which the
project owner approves one by one. This file turns them into filters; nothing
else in the repository may add a warning filter (``scripts/check_log_guard.py``
enforces that).

The list is validated while it is read, with the same code as the guard
``scripts/check_foreign_warnings.py``, so a test run refuses an entry that
would exempt this integration.

pytest loads this file by itself in every run that uses ``pyproject.toml``. A
run with a configuration file of its own further down (``tests/core``,
``tests/scripts``) does not look above that folder for ``conftest.py`` files, so
the ``conftest.py`` there calls :func:`install_foreign_warning_filters` itself.
Installing twice is harmless.
"""

import pytest

from scripts.check_foreign_warnings import EntryError, load_entries


def install_foreign_warning_filters(config: pytest.Config) -> None:
    """Add one ``ignore`` filter per approved foreign warning."""
    try:
        entries = load_entries()
    except EntryError as error:
        raise pytest.UsageError(f"tests/foreign_warnings.toml: {error}") from error
    installed = config.getini("filterwarnings")
    for entry in entries:
        if entry.as_filter() not in installed:
            config.addinivalue_line("filterwarnings", entry.as_filter())


def pytest_configure(config: pytest.Config) -> None:
    """Install the filters before the first test runs."""
    install_foreign_warning_filters(config)
