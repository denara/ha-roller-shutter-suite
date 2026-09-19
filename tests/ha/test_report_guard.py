"""The guard against logged deprecations sees what Home Assistant really logs.

Each test provokes a report on purpose, checks that the guard collected it and
then clears the list, because a report that stays in the list fails the test.
"""

import logging

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import frame
from homeassistant.loader import async_get_integration

from custom_components.roller_shutter_suite.const import DOMAIN


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
