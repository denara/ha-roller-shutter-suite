"""Every change sets the config entry up exactly once; an unchanged form does not."""

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.roller_shutter_suite as integration
from custom_components.roller_shutter_suite.const import (
    SUBENTRY_GROUP,
    SUBENTRY_WINDOW,
)
from tests.ha.helpers import (
    ROUTINE_HOUSE,
    add_group,
    add_window,
    routine_inherit,
    run_subentry_flow,
    set_cover,
    setup_entry,
)

INHERIT = routine_inherit()
CHANGED = routine_inherit({"schedule_evening_position": 0.0})


class SetupCounter:
    """Count how often Home Assistant sets the entry up."""

    count = 0


@pytest.fixture
def setups() -> Iterator[SetupCounter]:
    """Wrap the set-up of the integration with a counter."""
    counter = SetupCounter()
    original = integration.async_setup_entry

    async def counting(
        hass: HomeAssistant, entry: integration.RollerShutterSuiteConfigEntry
    ) -> bool:
        counter.count += 1
        return await original(hass, entry)

    with patch.object(integration, "async_setup_entry", counting):
        yield counter


async def test_each_change_sets_the_entry_up_exactly_once(
    hass: HomeAssistant, setups: SetupCounter
) -> None:
    """Create, reconfigure, rename and remove: one reload each, saved in the last step."""
    set_cover(hass, "cover.example_window")
    entry = await setup_entry(hass)
    assert setups.count == 1

    group = await add_group(hass, entry, "South", *INHERIT)
    assert setups.count == 2  # noqa: PLR2004 - the running count is the point

    window = await add_window(
        hass,
        entry,
        "Kitchen",
        ["cover.example_window"],
        *INHERIT,
        group_id=group.subentry_id,
    )
    assert setups.count == 3  # noqa: PLR2004

    # Title and data of the group change in one flow of two steps: one reload.
    await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_GROUP,
        [{"name": "South side"}, *CHANGED],
        reconfigure=group.subentry_id,
    )
    assert setups.count == 4  # noqa: PLR2004

    await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [
            {"name": "Kitchen window", "covers": ["cover.example_window"]},
            *CHANGED,
        ],
        reconfigure=window.subentry_id,
    )
    assert setups.count == 5  # noqa: PLR2004

    # The user interface renames a subentry outside any flow.
    hass.config_entries.async_update_subentry(
        entry, entry.subentries[window.subentry_id], title="Renamed"
    )
    await hass.async_block_till_done()
    assert setups.count == 6  # noqa: PLR2004
    assert entry.runtime_data.windows[window.subentry_id].title == "Renamed"

    assert hass.config_entries.async_remove_subentry(entry, window.subentry_id)
    await hass.async_block_till_done()
    assert setups.count == 7  # noqa: PLR2004


async def _save_the_house(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await entry.start_reconfigure_flow(hass)
    for user_input in ROUTINE_HOUSE:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input
        )
    await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_of_the_house_sets_up_exactly_once(
    hass: HomeAssistant, setups: SetupCounter
) -> None:
    """Five pages, one save in the last of them, one reload by the listener."""
    entry = await setup_entry(hass)

    await _save_the_house(hass, entry)

    assert setups.count == 2  # noqa: PLR2004


async def test_unchanged_forms_do_not_reload(
    hass: HomeAssistant, setups: SetupCounter
) -> None:
    """Saving a form without a change reloads nothing, on all three levels."""
    set_cover(hass, "cover.example_window")
    entry = await setup_entry(hass)
    await _save_the_house(hass, entry)
    group = await add_group(hass, entry, "South", *INHERIT)
    window = await add_window(
        hass, entry, "Kitchen", ["cover.example_window"], *INHERIT
    )
    before = setups.count

    await run_subentry_flow(
        hass, entry, SUBENTRY_GROUP, [{"name": "South"}, *INHERIT], group.subentry_id
    )
    await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [{"name": "Kitchen", "covers": ["cover.example_window"]}, *INHERIT],
        window.subentry_id,
    )
    await _save_the_house(hass, entry)

    assert setups.count == before
