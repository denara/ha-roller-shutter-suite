"""Versioned stored data: migration from the layout of an older version."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roller_shutter_suite.const import (
    CONF_COVERS,
    CONF_DRY_RUN,
    CONF_SETTINGS,
    CONFIG_MINOR_VERSION,
    CONFIG_VERSION,
    DOMAIN,
    ENTRY_TITLE,
    SUBENTRY_GROUP,
    SUBENTRY_WINDOW,
)
from tests.ha.helpers import set_cover, subentry_data


def _entry(version: int, minor_version: int, **kwargs: object) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=ENTRY_TITLE,
        version=version,
        minor_version=minor_version,
        **kwargs,
    )


async def test_entry_of_version_1_1_gets_the_settings_mapping(
    hass: HomeAssistant,
) -> None:
    """Version 1.1 stored nothing; 1.2 keeps settings in a mapping of their own."""
    set_cover(hass, "cover.example_window")
    entry = _entry(
        1,
        1,
        data={},
        subentries_data=[
            subentry_data(SUBENTRY_GROUP, "South", {}, "g1"),
            subentry_data(
                SUBENTRY_WINDOW,
                "Kitchen",
                {
                    CONF_COVERS: ["cover.example_window"],
                    CONF_DRY_RUN: False,
                    CONF_SETTINGS: {"morning_condition_source": "__none__"},
                },
                "w1",
            ),
        ],
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert (entry.version, entry.minor_version) == (
        CONFIG_VERSION,
        CONFIG_MINOR_VERSION,
    )
    assert entry.data == {CONF_SETTINGS: {}}
    assert entry.subentries["g1"].data == {CONF_SETTINGS: {}}
    # What is already there is left alone.
    assert entry.subentries["w1"].data == {
        CONF_COVERS: ["cover.example_window"],
        CONF_DRY_RUN: False,
        CONF_SETTINGS: {"morning_condition_source": "__none__"},
    }
    assert set(entry.runtime_data.windows) == {"w1"}


async def test_newer_minor_version_is_accepted_unchanged(hass: HomeAssistant) -> None:
    """After a downgrade the data stays as it is; unknown keys are reported at set-up."""
    data = {CONF_SETTINGS: {"example_from_the_future": 1}}
    entry = _entry(CONFIG_VERSION, CONFIG_MINOR_VERSION + 1, data=data)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.data == data
    assert entry.minor_version == CONFIG_MINOR_VERSION + 1


async def test_version_that_cannot_be_migrated_is_reported_by_raising(
    hass: HomeAssistant,
) -> None:
    """A version this code cannot start from ends in the state "migration error"."""
    entry = _entry(0, 1, data={})
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.MIGRATION_ERROR
    assert (entry.version, entry.minor_version) == (0, 1)
