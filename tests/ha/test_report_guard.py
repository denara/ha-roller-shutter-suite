"""The guard against logged deprecations sees what Home Assistant really logs.

Each test provokes a report on purpose, checks that the guard collected it and
then clears the list, because a report that stays in the list fails the test.
"""

import logging

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
