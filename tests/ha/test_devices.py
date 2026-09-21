"""One device per window, tied to exactly one subentry; removing the window removes it."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.roller_shutter_suite.const import DOMAIN
from tests.ha.helpers import (
    add_group,
    add_window,
    routine_inherit,
    set_cover,
    setup_entry,
)

INHERIT = routine_inherit()


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
    devices = dr.async_entries_for_config_entry(registry, entry.entry_id)

    assert {device.name for device in devices} == {"Left", "Right"}
    for window in (left, right):
        device = registry.async_get_device_by_identifier(
            (DOMAIN, window.subentry_id), entry.entry_id
        )
        assert device is not None
        assert device.config_entry_id == entry.entry_id
        assert device.config_subentry_id == window.subentry_id


async def test_renaming_a_window_renames_its_device(hass: HomeAssistant) -> None:
    """The title of the subentry is the name; the device follows at the next set-up."""
    set_cover(hass, "cover.example_window")
    entry = await setup_entry(hass)
    window = await add_window(
        hass, entry, "Kitchen", ["cover.example_window"], *INHERIT
    )

    hass.config_entries.async_update_subentry(entry, window, title="Dining room")
    await hass.async_block_till_done()

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert [device.name for device in devices] == ["Dining room"]


async def test_removing_a_window_removes_its_device(hass: HomeAssistant) -> None:
    """Home Assistant clears the registries of a removed subentry; nothing is left."""
    set_cover(hass, "cover.example_left")
    set_cover(hass, "cover.example_right")
    entry = await setup_entry(hass)
    left = await add_window(hass, entry, "Left", ["cover.example_left"], *INHERIT)
    await add_window(hass, entry, "Right", ["cover.example_right"], *INHERIT)

    assert hass.config_entries.async_remove_subentry(entry, left.subentry_id)
    await hass.async_block_till_done()

    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert [device.name for device in devices] == ["Right"]
