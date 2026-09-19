"""The guard against logged deprecations sees what Home Assistant really logs.

Each test provokes a report on purpose, checks that the guard collected it and
then clears the list, because a report that stays in the list fails the test.

The second half shows that raising a log level does not blind the guard. Four
ordinary ways of doing that are tried. For each, the report is still collected
while the level is raised, and the check that runs at the end of every test
names the state as a blind spot, which would fail a test that leaves it behind.
This is the only file that may use the fixtures and the helper of the guard.
"""

import logging
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import frame
from homeassistant.loader import async_get_integration

from custom_components.roller_shutter_suite.const import DOMAIN
from tests.ha.conftest import log_guard_blind_spots


async def test_usage_report_is_collected(
    hass: HomeAssistant, integration_reports: list[str]
) -> None:
    """A usage report of Home Assistant's frame helper is collected."""
    # The frame helper only blames integrations that Home Assistant has loaded.
    await async_get_integration(hass, DOMAIN)

    frame.report_usage(
        "does something that is only an example",
        integration_domain=DOMAIN,
        breaks_in_ha_version="2099.1",
    )

    assert len(integration_reports) == 1
    assert f"integration '{DOMAIN}'" in integration_reports[0]
    integration_reports.clear()


def test_deprecation_message_is_collected(integration_reports: list[str]) -> None:
    """A message in the format of Home Assistant's deprecation helper is collected."""
    logging.getLogger("homeassistant.helpers.example").warning(
        "The deprecated %s %s was %s from %s.%s Use %s instead, please %s",
        "function",
        "example_function",
        "called",
        DOMAIN,
        " It will be removed in HA Core 2099.1.",
        "other_function",
        "report it to the author",
    )

    assert len(integration_reports) == 1
    integration_reports.clear()


async def test_usage_report_without_a_version_is_collected(
    hass: HomeAssistant, integration_reports: list[str]
) -> None:
    """A usage report that names no version says neither "deprecated" nor "stop"."""
    await async_get_integration(hass, DOMAIN)

    frame.report_usage(
        "does something that is only an example",
        integration_domain=DOMAIN,
    )

    assert len(integration_reports) == 1
    assert "stop working" not in integration_reports[0]
    assert "deprecated" not in integration_reports[0].lower()
    integration_reports.clear()


def test_usage_report_of_another_core_module_is_collected(
    integration_reports: list[str],
) -> None:
    """The sentence of the frame helper counts on every logger.

    ``homeassistant.requirements`` logs it in exactly this form for a
    requirement that is going away; the word "deprecated" does not occur.
    """
    logging.getLogger("homeassistant.requirements").warning(
        "Detected that %sintegration '%s' %s. %s %s",
        "custom ",
        DOMAIN,
        "has requirement 'example==1.0' which is only an example",
        "This will stop working in Home Assistant 2099.1, please",
        f"report it to the author of the '{DOMAIN}' custom integration",
    )

    assert len(integration_reports) == 1
    assert "deprecated" not in integration_reports[0].lower()
    integration_reports.clear()


@pytest.mark.parametrize(
    "sentence",
    [
        "This will stop working in Home Assistant 2099.1",
        "This breaks in 2099.1",
        "It will be removed in HA Core 2099.1",
        "This is no longer supported",
        "Please report this issue",
    ],
)
def test_announcement_that_names_the_integration_is_collected(
    integration_reports: list[str], sentence: str
) -> None:
    """Every known way of announcing a removal is seen, on any logger."""
    logging.getLogger("homeassistant.helpers.example").warning(
        "Platform %s does something that is only an example. %s", DOMAIN, sentence
    )

    assert len(integration_reports) == 1
    integration_reports.clear()


async def test_report_that_names_only_the_issue_tracker_is_collected(
    hass: HomeAssistant, integration_reports: list[str]
) -> None:
    """Home Assistant may point at the issue tracker instead of the domain."""
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.issue_tracker

    logging.getLogger("homeassistant.helpers.example").warning(
        "Entity does something that is only an example, please create a bug "
        "report at %s",
        integration.issue_tracker,
    )

    assert len(integration_reports) == 1
    integration_reports.clear()


def test_ordinary_message_about_the_integration_is_ignored(
    integration_reports: list[str],
) -> None:
    """Naming the integration is not enough; the message must be a report."""
    logging.getLogger("homeassistant.setup").info("Setting up %s", DOMAIN)

    assert integration_reports == []


def test_reports_about_other_integrations_are_ignored(
    integration_reports: list[str],
) -> None:
    """Deprecated usage in somebody else's integration does not fail our tests."""
    logging.getLogger("homeassistant.helpers.frame").warning(
        "Detected that custom integration 'another_integration' does something"
    )
    logging.getLogger("homeassistant.helpers.example").warning(
        "The deprecated function example_function was called from "
        "another_integration. Use other_function instead"
    )

    assert integration_reports == []


FRAME_LOGGER = "homeassistant.helpers.frame"


@contextmanager
def _root_level_through_caplog(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """``caplog.set_level`` without a logger raises the level of the root logger."""
    root = logging.getLogger()
    before = root.level
    caplog.set_level(logging.ERROR)
    try:
        yield
    finally:
        root.setLevel(before)


@contextmanager
def _caplog_at_level(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    with caplog.at_level(logging.ERROR):
        yield


@contextmanager
def _logging_disabled(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    logging.disable(logging.WARNING)
    try:
        yield
    finally:
        logging.disable(logging.NOTSET)


@contextmanager
def _frame_logger_level(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    logger = logging.getLogger(FRAME_LOGGER)
    before = logger.level
    logger.setLevel(logging.ERROR)
    try:
        yield
    finally:
        logger.setLevel(before)


RAISED_LEVELS = [
    pytest.param(_root_level_through_caplog, id="caplog.set_level"),
    pytest.param(_caplog_at_level, id="caplog.at_level"),
    pytest.param(_logging_disabled, id="logging.disable"),
    pytest.param(_frame_logger_level, id="setLevel on the frame logger"),
]
type RaisedLevel = Callable[[pytest.LogCaptureFixture], AbstractContextManager[None]]


@pytest.mark.parametrize("raised_level", RAISED_LEVELS)
async def test_report_is_collected_while_a_log_level_is_raised(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    integration_reports: list[str],
    raised_level: RaisedLevel,
) -> None:
    """Home Assistant still creates the record, and the guard still gets it."""
    await async_get_integration(hass, DOMAIN)

    with raised_level(caplog):
        frame.report_usage(
            "does something that is only an example",
            integration_domain=DOMAIN,
            breaks_in_ha_version="2099.1",
        )

    assert len(integration_reports) == 1
    integration_reports.clear()


@pytest.mark.parametrize("raised_level", RAISED_LEVELS)
def test_raised_log_level_is_a_blind_spot_at_the_end_of_a_test(
    caplog: pytest.LogCaptureFixture,
    log_guard_collector: logging.Handler,
    raised_level: RaisedLevel,
) -> None:
    """A test that ends in such a state fails, whatever it logged."""
    assert log_guard_blind_spots(log_guard_collector) == []

    with raised_level(caplog):
        assert log_guard_blind_spots(log_guard_collector) != []

    assert log_guard_blind_spots(log_guard_collector) == []


def test_removed_handler_and_cut_off_logger_are_blind_spots(
    log_guard_collector: logging.Handler,
) -> None:
    """Taking the handler away or cutting a logger off is noticed as well."""
    root = logging.getLogger()
    root.removeHandler(log_guard_collector)
    assert len(log_guard_blind_spots(log_guard_collector)) == 1
    root.addHandler(log_guard_collector)

    logger = logging.getLogger("homeassistant.helpers")
    logger.propagate = False
    assert len(log_guard_blind_spots(log_guard_collector)) == 2  # noqa: PLR2004
    logger.propagate = True

    assert log_guard_blind_spots(log_guard_collector) == []
