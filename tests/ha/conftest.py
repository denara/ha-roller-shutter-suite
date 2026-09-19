"""Fixtures for the tests that run inside the Home Assistant test harness.

Everything here is active for every test under ``tests/ha/`` without being
requested.
"""

import json
import logging
from collections.abc import Iterator
from pathlib import Path

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
# writes log records, which ``filterwarnings = error`` cannot see. The formats
# below were read in the Core source at the tested tag (2026.9.2):
#
# - ``homeassistant.helpers.frame.report_usage`` logs on the logger of its own
#   module: "Detected that custom integration '<domain>' <what> at <file>, line
#   <n>: <code>. This will stop working in Home Assistant <version>, please
#   <report it ...>". Without a version the last sentence is only "Please
#   <report it ...>", so such a report contains neither "deprecated" nor
#   "stop working".
# - Other Core modules use the same sentence on their own logger, for example
#   ``homeassistant.requirements`` for a requirement that is going away.
# - ``homeassistant.helpers.deprecation`` (deprecated functions, classes,
#   constants, aliases, arguments) logs on the logger of the module that owns
#   the deprecated name: "The deprecated <kind> <name> was <used> from <domain>.
#   It will be removed in HA Core <version>. ...". Its older helpers log
#   "'<name>' is deprecated. ..." on the logger of the calling module, which
#   for this integration starts with ``custom_components.<domain>``.
# - ``homeassistant.loader.async_suggest_report_issue`` writes the request that
#   ends most of these messages: "create a bug report at <issue tracker>" or
#   "report it to the author of the '<domain>' custom integration". A message
#   may therefore name this integration only through its issue tracker.
_FRAME_LOGGER = "homeassistant.helpers.frame"
_INTEGRATION_LOGGER = f"custom_components.{DOMAIN}"
_MANIFEST = json.loads(
    (
        Path(__file__).parents[2] / "custom_components" / DOMAIN / "manifest.json"
    ).read_text(encoding="utf-8")
)
_ISSUE_TRACKER: str = _MANIFEST["issue_tracker"]

# A record that names this integration is a report when it comes from the frame
# helper or contains one of these phrases (compared in lower case). The list
# may grow; it must never shrink.
_REPORT_PHRASES = (
    "deprecated",
    "detected that",
    "will stop working",
    "stop working in",
    "breaks in",
    "will be removed",
    "no longer supported",
    "please report",
    "report it to",
    "create a bug report",
)


def _names_this_integration(record: logging.LogRecord, message: str) -> bool:
    """Tell whether a log record is about this integration."""
    return (
        DOMAIN in message
        or _ISSUE_TRACKER in message
        or record.name == _INTEGRATION_LOGGER
        or record.name.startswith(f"{_INTEGRATION_LOGGER}.")
    )


def _is_report_about_this_integration(record: logging.LogRecord) -> bool:
    """Tell whether Home Assistant blames this integration in a log record."""
    message = record.getMessage()
    if not _names_this_integration(record, message):
        return False
    lowered = message.lower()
    return record.name == _FRAME_LOGGER or any(
        phrase in lowered for phrase in _REPORT_PHRASES
    )


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
