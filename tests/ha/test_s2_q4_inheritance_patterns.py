"""SPIKE S2, question 4: three inheritance patterns on real forms.

Every pattern has to pass the same three trials: a boolean is overridden and
returned to "inherit"; a number is set to zero, which is a valid value; and the
inherited value comes from two levels up when the group says nothing.
The inputs are what the frontend submits: it leaves out fields that are empty.
"""

from typing import Any

import probatio
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roller_shutter_suite.const import (
    CONF_SETTINGS,
    SUBENTRY_PATTERN_LAB,
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


async def lab(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    pattern: str,
    inputs: list[dict[str, Any]],
    reconfigure: ConfigSubentry | None = None,
) -> dict[str, Any]:
    """Run the pattern lab; a new flow first picks the pattern in the menu."""
    if reconfigure is None:
        inputs = [{"next_step_id": pattern}, *inputs]
    return await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_PATTERN_LAB,
        inputs,
        reconfigure=None if reconfigure is None else reconfigure.subentry_id,
    )


def lab_entry(entry: MockConfigEntry) -> ConfigSubentry:
    """Return the lab subentry."""
    return next(
        s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_PATTERN_LAB
    )


# --- pattern (a): empty means inherit -------------------------------------------


async def test_pattern_a_shows_inherited_values_from_two_levels(
    hass: HomeAssistant,
) -> None:
    """The group sets one value; the other comes from the house."""
    entry = await setup_entry(hass)
    await add_group(hass, entry, "South", {"open_in_morning": "off"})

    form = await lab(hass, entry, "pattern_a", [])

    # The boolean is a drop-down whose "inherit" entry names the inherited state.
    switch = form["data_schema"].schema[marker_of(form, "open_in_morning")]
    assert switch.config["options"] == ["inherit_off", "on", "off"]
    assert switch.config["translation_key"] == "inherited_switch"
    assert marker_of(form, "open_in_morning").default() == "inherit_off"
    # The number is optional and empty; the helper text gets value and source.
    assert isinstance(marker_of(form, "morning_position"), probatio.Optional)
    assert marker_of(form, "morning_position").description is None
    placeholders = form["description_placeholders"]
    assert placeholders["open_in_morning_source"] == "South"
    assert placeholders["morning_position_inherited"] == "100 %"
    assert placeholders["morning_position_source"] == "Roller Shutter Suite"


async def test_pattern_a_boolean_round_trip_and_zero(hass: HomeAssistant) -> None:
    """Override both, reopen, return both to inherit."""
    entry = await setup_entry(hass)

    created = await lab(
        hass,
        entry,
        "pattern_a",
        [{"open_in_morning": "off", "morning_position": 0, "expert": {}}],
    )
    assert created["type"] is FlowResultType.CREATE_ENTRY
    assert lab_entry(entry).data[CONF_SETTINGS] == {
        "open_in_morning": False,
        "morning_position": 0,
    }

    # Reopened: the own values are visible, zero included.
    form = await lab(hass, entry, "pattern_a", [], reconfigure=lab_entry(entry))
    assert marker_of(form, "open_in_morning").default() == "off"
    assert marker_of(form, "morning_position").description == {"suggested_value": 0}

    # Back to inherit: pick "inherit" and empty the number (the frontend then
    # leaves the key out).
    await lab(
        hass,
        entry,
        "pattern_a",
        [{"open_in_morning": "inherit_on", "expert": {}}],
        reconfigure=lab_entry(entry),
    )
    assert lab_entry(entry).data[CONF_SETTINGS] == {}


async def test_pattern_a_in_the_window_flow_over_two_levels(
    hass: HomeAssistant,
) -> None:
    """The real window flow: group value shown, overridden, returned."""
    entry = await setup_entry(hass)
    set_cover(hass, "cover.example_window")
    group = await add_group(hass, entry, "South", {"morning_position": 60})
    window = await add_window(
        hass,
        entry,
        "Example window",
        ["cover.example_window"],
        group.subentry_id,
        {"morning_position": 0},
    )
    assert window.data[CONF_SETTINGS] == {"morning_position": 0}

    basics = {
        "name": "Example window",
        "covers": ["cover.example_window"],
        "group_id": group.subentry_id,
    }
    form = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [basics, INHERIT_ALL_SWITCHES],
        reconfigure=window.subentry_id,
    )
    assert form["description_placeholders"]["morning_position_inherited"] == "60 %"
    assert form["description_placeholders"]["morning_position_source"] == "South"
    assert form["description_placeholders"]["evening_position_source"] == (
        "Roller Shutter Suite"
    )
    assert marker_of(form, "morning_position").description == {"suggested_value": 0}

    await hass.config_entries.subentries.async_configure(
        form["flow_id"], {"open_in_morning": "inherit_on", "expert": {}}
    )
    await hass.async_block_till_done()
    assert entry.subentries[window.subentry_id].data[CONF_SETTINGS] == {}


# --- pattern (b): a switch per value --------------------------------------------


async def test_pattern_b_round_trip(hass: HomeAssistant) -> None:
    """The value field shows the effective value; the toggle decides."""
    entry = await setup_entry(hass)
    await add_group(hass, entry, "South", {"morning_position": 60})

    form = await lab(hass, entry, "pattern_b", [])
    assert schema_keys(form) == [
        "override_open_in_morning",
        "open_in_morning",
        "override_morning_position",
        "morning_position",
        "override_random_offset",
        "random_offset",
    ]
    assert marker_of(form, "morning_position").default() == 60
    assert marker_of(form, "override_morning_position").default() is False

    untouched = {
        "override_open_in_morning": False,
        "open_in_morning": True,
        "override_morning_position": False,
        "morning_position": 60,
        "override_random_offset": False,
        "random_offset": 0,
    }
    # The trap: a changed value with the toggle off.
    result = await hass.config_entries.subentries.async_configure(
        form["flow_id"], untouched | {"morning_position": 0}
    )
    assert result["errors"] == {"morning_position": "changed_without_override"}

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        untouched
        | {
            "override_open_in_morning": True,
            "open_in_morning": False,
            "override_morning_position": True,
            "morning_position": 0,
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert lab_entry(entry).data[CONF_SETTINGS] == {
        "open_in_morning": False,
        "morning_position": 0,
    }

    # Back to inherit: switch the toggles off. The stale values next to them
    # differ from the inherited ones, so the user also has to reset them or
    # the form complains: a second trap.
    result = await lab(
        hass,
        entry,
        "pattern_b",
        [untouched | {"open_in_morning": False}],
        reconfigure=lab_entry(entry),
    )
    assert result["errors"] == {"open_in_morning": "changed_without_override"}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], untouched
    )
    await hass.async_block_till_done()
    assert lab_entry(entry).data[CONF_SETTINGS] == {}


# --- pattern (c): a list of own values -------------------------------------------


async def test_pattern_c_round_trip(hass: HomeAssistant) -> None:
    """Pick the settings, then fill in only those."""
    entry = await setup_entry(hass)
    await add_group(hass, entry, "South", {"morning_position": 60})

    form = await lab(hass, entry, "pattern_c", [])
    assert schema_keys(form) == ["overridden"]
    assert form["description_placeholders"]["morning_position_inherited"] == "60 %"

    values = await hass.config_entries.subentries.async_configure(
        form["flow_id"], {"overridden": ["open_in_morning", "morning_position"]}
    )
    assert values["step_id"] == "pattern_c_values"
    assert schema_keys(values) == ["open_in_morning", "morning_position"]
    # The fields start with the inherited values.
    assert marker_of(values, "morning_position").default() == 60

    result = await hass.config_entries.subentries.async_configure(
        values["flow_id"], {"open_in_morning": False, "morning_position": 0}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert lab_entry(entry).data[CONF_SETTINGS] == {
        "open_in_morning": False,
        "morning_position": 0,
    }

    # Back to inherit: take the entries off the list (an emptied list is left
    # out by the frontend); the second step is skipped.
    form = await lab(hass, entry, "pattern_c", [], reconfigure=lab_entry(entry))
    assert marker_of(form, "overridden").description == {
        "suggested_value": ["open_in_morning", "morning_position"]
    }
    result = await hass.config_entries.subentries.async_configure(form["flow_id"], {})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.ABORT
    assert lab_entry(entry).data[CONF_SETTINGS] == {}
