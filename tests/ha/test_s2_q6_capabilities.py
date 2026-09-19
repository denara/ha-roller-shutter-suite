"""SPIKE S2, question 6: an option the hardware cannot support.

The field is left out. A read-only stand-in ``<key>_unavailable`` takes its
place; its translated label and helper text carry the reason, and a placeholder
names the cover that limits the window.
"""

import json
from pathlib import Path

from homeassistant.components.cover import CoverEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.selector import BooleanSelector

from custom_components.roller_shutter_suite.const import CONF_SETTINGS, SUBENTRY_WINDOW
from tests.ha.s2_helpers import (
    FULL_COVER,
    marker_of,
    run_subentry_flow,
    schema_keys,
    set_cover,
    setup_entry,
)

BUTTONS_ON = {
    "enable_daily_routine": "off",
    "enable_shading": "inherit_off",
    "enable_buttons": "on",
}
STRINGS = (
    Path(__file__).parents[2]
    / "custom_components"
    / "roller_shutter_suite"
    / "strings.json"
)


async def test_option_is_replaced_by_a_read_only_reason(hass: HomeAssistant) -> None:
    """One of two members cannot stop, so hold-to-move is not offered."""
    entry = await setup_entry(hass)
    set_cover(hass, "cover.example_left")
    set_cover(hass, "cover.example_roof", FULL_COVER & ~CoverEntityFeature.STOP)

    form = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [
            {
                "name": "Example window",
                "covers": ["cover.example_left", "cover.example_roof"],
            },
            BUTTONS_ON,
        ],
    )

    assert form["step_id"] == "feature_buttons"
    assert schema_keys(form) == ["hold_to_move_unavailable", "double_press_position"]
    stand_in = form["data_schema"].schema[marker_of(form, "hold_to_move_unavailable")]
    assert isinstance(stand_in, BooleanSelector)
    assert stand_in.config == {"read_only": True}
    assert form["description_placeholders"]["limited_by_stop"] == "cover.example_roof"

    # The reason is a translated string that uses the placeholder.
    step = json.loads(STRINGS.read_text(encoding="utf-8"))["config_subentries"][
        "window"
    ]["step"]["feature_buttons"]
    assert "{limited_by_stop}" in step["data_description"]["hold_to_move_unavailable"]

    # The frontend does not submit read-only fields; a client that does is not
    # able to smuggle a value in either.
    result = await hass.config_entries.subentries.async_configure(
        form["flow_id"], {"hold_to_move_unavailable": True, "double_press_position": 0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SETTINGS] == {
        "enable_daily_routine": False,
        "enable_buttons": True,
        "double_press_position": 0,
    }


async def test_option_is_offered_when_every_member_supports_it(
    hass: HomeAssistant,
) -> None:
    """The same step for covers that can stop."""
    entry = await setup_entry(hass)
    set_cover(hass, "cover.example_left")

    form = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [{"name": "Example window", "covers": ["cover.example_left"]}, BUTTONS_ON],
    )

    assert schema_keys(form) == ["hold_to_move", "double_press_position"]
