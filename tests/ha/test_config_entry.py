"""Set-up, single-instance rule and unloading of the config entry."""

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roller_shutter_suite.const import DOMAIN, ENTRY_TITLE


async def test_user_flow_creates_entry_that_sets_up(hass: HomeAssistant) -> None:
    """The user flow creates the entry, and Home Assistant sets it up."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == ENTRY_TITLE
    assert result["data"] == {}
    assert result["result"].state is ConfigEntryState.LOADED


async def test_entry_sets_up(hass: HomeAssistant) -> None:
    """An existing entry is set up and carries its runtime data."""
    entry = MockConfigEntry(domain=DOMAIN, title=ENTRY_TITLE, data={})
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not None


async def test_second_entry_is_refused(hass: HomeAssistant) -> None:
    """Home Assistant refuses a second entry: the manifest allows only one."""
    entry = MockConfigEntry(domain=DOMAIN, title=ENTRY_TITLE, data={})
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_entry_unloads(hass: HomeAssistant) -> None:
    """A loaded entry unloads cleanly."""
    entry = MockConfigEntry(domain=DOMAIN, title=ENTRY_TITLE, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
