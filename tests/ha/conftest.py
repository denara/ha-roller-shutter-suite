"""Fixtures for the tests that run inside the Home Assistant test harness.

Everything here is active for every test under ``tests/ha/`` without being
requested.
"""

import logging
from collections.abc import Iterator

import pytest

# This import also decides which ``custom_components`` package Home Assistant
# sees. The test plugin ships a ``custom_components`` package of its own in its
# test configuration folder, and the ``hass`` fixture puts that folder at the
# front of the import path while it imports ``custom_components``. Whichever
# package was imported first stays in ``sys.modules`` and wins. pytest loads
# this file before any test of this folder is set up, so the repository's
# folder wins. An empty ``custom_components/__init__.py`` would not change the
# outcome; ``test_harness.py`` guards the result.
from custom_components.roller_shutter_suite.const import DOMAIN

# Home Assistant 2026.9 never raises a Python warning for deprecated usage; it
# writes log records, which ``filterwarnings = error`` cannot see:
#
# - ``homeassistant.helpers.frame.report_usage`` logs on the logger of its own
#   module: "Detected that custom integration '<domain>' <what> at <file>, line
#   <n>: <code>. This will stop working in Home Assistant <version>, ...".
# - ``homeassistant.helpers.deprecation`` (deprecated functions, classes,
#   constants, aliases, arguments) logs on the logger of the module that owns
#   the deprecated name: "The deprecated <kind> <name> was <used> from <domain>.
#   ...". Its older helpers log "'<name>' is deprecated. ..." on the logger of
#   the calling module, which for this integration starts with
#   ``custom_components.<domain>``.
_FRAME_LOGGER = "homeassistant.helpers.frame"
_INTEGRATION_LOGGER = f"custom_components.{DOMAIN}"


def _names_this_integration(record: logging.LogRecord, message: str) -> bool:
    """Tell whether a log record is about this integration."""
    return (
        DOMAIN in message
        or record.name == _INTEGRATION_LOGGER
        or record.name.startswith(f"{_INTEGRATION_LOGGER}.")
    )


def _is_report_about_this_integration(record: logging.LogRecord) -> bool:
    """Tell whether Home Assistant blames this integration in a log record."""
    message = record.getMessage()
    if not _names_this_integration(record, message):
        return False
    return record.name == _FRAME_LOGGER or "deprecated" in message.lower()


class _ReportCollector(logging.Handler):
    """Collect usage reports and deprecation messages about this integration."""

    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)
        self.reports: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if _is_report_about_this_integration(record):
            self.reports.append(f"{record.name}: {record.getMessage()}")


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load integrations from ``custom_components``."""


@pytest.fixture
def integration_reports() -> Iterator[list[str]]:
    """Collect what Home Assistant logs about this integration during a test.

    The handler sits on the root logger instead of using ``caplog``, so a test
    that clears or reconfigures ``caplog`` cannot hide a report. A test that
    provokes a report on purpose asserts on this list and then clears it.
    """
    collector = _ReportCollector()
    root_logger = logging.getLogger()
    root_logger.addHandler(collector)
    try:
        yield collector.reports
    finally:
        root_logger.removeHandler(collector)


@pytest.fixture(autouse=True)
def fail_on_logged_deprecation(integration_reports: list[str]) -> Iterator[None]:
    """Fail the test when Home Assistant logged a report about this integration."""
    yield
    if integration_reports:
        pytest.fail(
            "Home Assistant logged a deprecation or usage report about "
            f"'{DOMAIN}':\n" + "\n".join(integration_reports),
            pytrace=False,
        )
