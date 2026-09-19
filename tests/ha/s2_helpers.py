"""SPIKE S2: helpers that drive the flows the way the frontend does."""

from typing import Any

from homeassistant.components.cover import CoverEntityFeature
from homeassistant.config_entries import SOURCE_USER, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roller_shutter_suite.config_flow import default_settings
from custom_components.roller_shutter_suite.const import (
    CONF_SETTINGS,
    DATA_SETUP_COUNT,
    DOMAIN,
    ENTRY_TITLE,
    SUBENTRY_GROUP,
    SUBENTRY_WINDOW,
)

FULL_COVER = (
    CoverEntityFeature.OPEN
    | CoverEntityFeature.CLOSE
    | CoverEntityFeature.STOP
    | CoverEntityFeature.SET_POSITION
)
# "Inherit" for the three feature switches, whatever the inherited state is.
INHERIT_ALL_SWITCHES = {
    "enable_daily_routine": "inherit_on",
    "enable_shading": "inherit_off",
    "enable_buttons": "inherit_off",
}


def set_cover(
    hass: HomeAssistant,
    entity_id: str,
    features: CoverEntityFeature = FULL_COVER,
    position: int | None = 100,
) -> None:
    """Put a cover state on the state machine, as a cover platform would."""
    attributes: dict[str, Any] = {"supported_features": int(features)}
    if position is not None:
        attributes["current_position"] = position
    hass.states.async_set(entity_id, "open", attributes)


async def setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create and set up the house entry with its default values."""
    entry = MockConfigEntry(
        domain=DOMAIN, title=ENTRY_TITLE, data={CONF_SETTINGS: default_settings()}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def setup_count(hass: HomeAssistant) -> int:
    """Return how often the entry has been set up."""
    count: int = hass.data.get(DATA_SETUP_COUNT, 0)
    return count


def schema_keys(result: dict[str, Any]) -> list[str]:
    """Return the top-level field names of a form."""
    return [str(marker) for marker in result["data_schema"].schema]


def marker_of(result: dict[str, Any], key: str) -> Any:
    """Return the schema marker of a top-level field."""
    return next(m for m in result["data_schema"].schema if str(m) == key)


async def run_subentry_flow(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    subentry_type: str,
    inputs: list[dict[str, Any]],
    reconfigure: str | None = None,
) -> dict[str, Any]:
    """Start a subentry flow, feed it one input per step, return the last result."""
    if reconfigure is None:
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, subentry_type), context={"source": SOURCE_USER}
        )
    else:
        result = await entry.start_subentry_reconfigure_flow(hass, reconfigure)
    for user_input in inputs:
        assert result["type"] in (FlowResultType.FORM, FlowResultType.MENU), result
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"], user_input
        )
    await hass.async_block_till_done()
    return dict(result)


async def add_group(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    name: str,
    routine: dict[str, Any] | None = None,
) -> ConfigSubentry:
    """Add a group through its flow; ``routine`` is the daily routine input."""
    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_GROUP,
        [
            {"name": name},
            INHERIT_ALL_SWITCHES,
            {"open_in_morning": "inherit_on", "expert": {}} | (routine or {}),
        ],
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    return next(s for s in entry.subentries.values() if s.title == name)


async def add_window(  # noqa: PLR0913, PLR0917
    hass: HomeAssistant,
    entry: MockConfigEntry,
    name: str,
    covers: list[str],
    group_id: str | None = None,
    routine: dict[str, Any] | None = None,
) -> ConfigSubentry:
    """Add a window through its flow."""
    basics: dict[str, Any] = {"name": name, "covers": covers}
    if group_id is not None:
        basics["group_id"] = group_id
    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [
            basics,
            INHERIT_ALL_SWITCHES,
            {"open_in_morning": "inherit_on", "expert": {}} | (routine or {}),
        ],
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    return next(s for s in entry.subentries.values() if s.title == name)
