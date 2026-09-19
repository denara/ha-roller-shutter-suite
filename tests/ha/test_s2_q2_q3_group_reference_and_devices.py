"""SPIKE S2, questions 2 and 3: the group reference, its loss, and devices."""

import probatio
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.selector import SelectSelector

from custom_components.roller_shutter_suite.const import (
    CONF_GROUP_ID,
    DOMAIN,
    SUBENTRY_WINDOW,
)
from tests.ha.s2_helpers import (
    INHERIT_ALL_SWITCHES,
    add_group,
    add_window,
    marker_of,
    run_subentry_flow,
    schema_keys,
    set_cover,
    setup_entry,
)

SENSOR = "sensor.example_window_effective_morning_position"


async def test_group_is_chosen_from_the_groups_that_exist(hass: HomeAssistant) -> None:
    """The options of the group field are built when the form is shown."""
    entry = await setup_entry(hass)

    form = await run_subentry_flow(hass, entry, SUBENTRY_WINDOW, [])
    assert CONF_GROUP_ID not in schema_keys(form)

    south = await add_group(hass, entry, "South")
    west = await add_group(hass, entry, "West")
    form = await run_subentry_flow(hass, entry, SUBENTRY_WINDOW, [])
    selector = form["data_schema"].schema[marker_of(form, CONF_GROUP_ID)]
    assert isinstance(selector, SelectSelector)
    assert selector.config["options"] == [
        {"value": south.subentry_id, "label": "South"},
        {"value": west.subentry_id, "label": "West"},
    ]
    # Optional, without a default: leaving it empty means "no group".
    assert isinstance(marker_of(form, CONF_GROUP_ID), probatio.Optional)


async def test_value_is_inherited_over_two_levels_at_runtime(
    hass: HomeAssistant,
) -> None:
    """House -> group -> window, seen through the dummy sensor."""
    entry = await setup_entry(hass)
    set_cover(hass, "cover.example_window")
    group = await add_group(hass, entry, "South")
    await add_window(
        hass, entry, "Example window", ["cover.example_window"], group.subentry_id
    )

    # Nothing overridden: the house default.
    assert float(hass.states.get(SENSOR).state) == 100  # type: ignore[union-attr]

    await run_subentry_flow(
        hass,
        entry,
        "group",
        [
            {"name": "South"},
            INHERIT_ALL_SWITCHES,
            {"open_in_morning": "inherit_on", "morning_position": 60, "expert": {}},
        ],
        reconfigure=group.subentry_id,
    )
    assert float(hass.states.get(SENSOR).state) == 60  # type: ignore[union-attr]


async def test_removing_a_group_cannot_be_refused_and_falls_back(
    hass: HomeAssistant,
) -> None:
    """The window of a removed group inherits from the house; an issue says so."""
    entry = await setup_entry(hass)
    set_cover(hass, "cover.example_window")
    group = await add_group(hass, entry, "South", {"morning_position": 60})
    window = await add_window(
        hass, entry, "Example window", ["cover.example_window"], group.subentry_id
    )
    assert float(hass.states.get(SENSOR).state) == 60  # type: ignore[union-attr]

    # Home Assistant removes the subentry without asking the integration.
    assert hass.config_entries.async_remove_subentry(entry, group.subentry_id)
    await hass.async_block_till_done()

    assert float(hass.states.get(SENSOR).state) == 100  # type: ignore[union-attr]
    assert entry.runtime_data.dangling == {window.subentry_id}
    issue_id = f"dangling_group_{window.subentry_id}"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders == {"window": "Example window"}

    # Saving the window's form without a group repairs the reference.
    await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [
            {"name": "Example window", "covers": ["cover.example_window"]},
            INHERIT_ALL_SWITCHES,
            {"open_in_morning": "inherit_on", "expert": {}},
        ],
        reconfigure=window.subentry_id,
    )
    assert entry.subentries[window.subentry_id].data[CONF_GROUP_ID] is None
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def test_groups_and_windows_each_own_one_device(hass: HomeAssistant) -> None:
    """One device per subentry; removing the subentry removes device and entity."""
    entry = await setup_entry(hass)
    set_cover(hass, "cover.example_window")
    group = await add_group(hass, entry, "South")
    window = await add_window(
        hass, entry, "Example window", ["cover.example_window"], group.subentry_id
    )

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert {device.config_subentry_id: device.name for device in devices} == {
        group.subentry_id: "South",
        window.subentry_id: "Example window",
    }
    window_device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, window.subentry_id), entry.entry_id
    )
    assert window_device is not None
    assert window_device.config_entry_id == entry.entry_id

    sensor = er.async_get(hass).async_get(SENSOR)
    assert sensor is not None
    assert sensor.config_subentry_id == window.subentry_id
    assert sensor.device_id == window_device.id

    hass.config_entries.async_remove_subentry(entry, window.subentry_id)
    await hass.async_block_till_done()

    assert er.async_get(hass).async_get(SENSOR) is None
    remaining = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert [device.config_subentry_id for device in remaining] == [group.subentry_id]
