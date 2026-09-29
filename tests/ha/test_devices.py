"""The devices: one per window, one per group, one for the house.

A window's device belongs to exactly its subentry. A group has a device of
its own that belongs to the group's subentry and holds its controls; a group
owns no window device. The house has a device that belongs to the config
entry and to no subentry. Group and house devices are service devices.
Removing a subentry removes its device.
"""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType

from custom_components.roller_shutter_suite.const import DOMAIN, ENTRY_TITLE
from tests.ha.helpers import (
    add_group,
    add_window,
    routine_inherit,
    set_cover,
    setup_entry,
)

INHERIT = routine_inherit()


def _names(hass: HomeAssistant, entry_id: str) -> set[str | None]:
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry_id)
    return {device.name for device in devices}


async def test_window_device_belongs_to_exactly_one_subentry(
    hass: HomeAssistant,
) -> None:
    """Each window has its own device; a group owns no window device."""
    set_cover(hass, "cover.example_left")
    set_cover(hass, "cover.example_right")
    entry = await setup_entry(hass)
    group = await add_group(hass, entry, "South", *INHERIT)
    left = await add_window(
        hass,
        entry,
        "Left",
        ["cover.example_left"],
        *INHERIT,
        group_id=group.subentry_id,
    )
    right = await add_window(hass, entry, "Right", ["cover.example_right"], *INHERIT)

    registry = dr.async_get(hass)

    assert _names(hass, entry.entry_id) == {ENTRY_TITLE, "South", "Left", "Right"}
    for window in (left, right):
        device = registry.async_get_device_by_identifier(
            (DOMAIN, window.subentry_id), entry.entry_id
        )
        assert device is not None
        assert device.config_entry_id == entry.entry_id
        assert device.config_subentry_id == window.subentry_id
        assert device.entry_type is None


async def test_the_house_and_every_group_have_a_service_device_of_their_own(
    hass: HomeAssistant,
) -> None:
    """The house belongs to the entry and no subentry; a group to its subentry."""
    entry = await setup_entry(hass)
    group = await add_group(hass, entry, "South", *INHERIT)
    registry = dr.async_get(hass)

    house = registry.async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    assert house is not None
    assert house.name == ENTRY_TITLE
    assert house.config_entry_id == entry.entry_id
    assert house.config_subentry_id is None
    assert house.entry_type is DeviceEntryType.SERVICE
    south = registry.async_get_device_by_identifier(
        (DOMAIN, group.subentry_id), entry.entry_id
    )
    assert south is not None
    assert south.name == "South"
    assert south.config_subentry_id == group.subentry_id
    assert south.entry_type is DeviceEntryType.SERVICE


async def test_renaming_a_window_renames_its_device(hass: HomeAssistant) -> None:
    """The title of the subentry is the name; the device follows at the next set-up."""
    set_cover(hass, "cover.example_window")
    entry = await setup_entry(hass)
    window = await add_window(
        hass, entry, "Kitchen", ["cover.example_window"], *INHERIT
    )
    group = await add_group(hass, entry, "South", *INHERIT)

    hass.config_entries.async_update_subentry(entry, window, title="Dining room")
    await hass.async_block_till_done()
    hass.config_entries.async_update_subentry(entry, group, title="North")
    await hass.async_block_till_done()

    assert _names(hass, entry.entry_id) == {ENTRY_TITLE, "North", "Dining room"}


async def test_removing_a_window_or_a_group_removes_its_device(
    hass: HomeAssistant,
) -> None:
    """Home Assistant clears the registries of a removed subentry; nothing is left."""
    set_cover(hass, "cover.example_left")
    set_cover(hass, "cover.example_right")
    entry = await setup_entry(hass)
    left = await add_window(hass, entry, "Left", ["cover.example_left"], *INHERIT)
    await add_window(hass, entry, "Right", ["cover.example_right"], *INHERIT)
    group = await add_group(hass, entry, "South", *INHERIT)

    assert hass.config_entries.async_remove_subentry(entry, left.subentry_id)
    await hass.async_block_till_done()
    assert hass.config_entries.async_remove_subentry(entry, group.subentry_id)
    await hass.async_block_till_done()

    assert _names(hass, entry.entry_id) == {ENTRY_TITLE, "Right"}
