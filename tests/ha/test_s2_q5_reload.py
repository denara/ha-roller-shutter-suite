"""SPIKE S2, question 5: a change is applied by exactly one set-up.

The entry registers an update listener that schedules the reload; every flow
ends with ``async_update_and_abort`` (or ``async_create_entry``) and never with
a reloading method. The autouse log guard of ``conftest.py`` fails each of these
tests if Home Assistant logs a deprecation about the integration.
"""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.roller_shutter_suite.const import (
    CONF_SETTINGS,
    SUBENTRY_GROUP,
    SUBENTRY_WINDOW,
)
from custom_components.roller_shutter_suite.flow.group_flow import GroupSubentryFlow
from tests.ha.s2_helpers import (
    INHERIT_ALL_SWITCHES,
    add_group,
    add_window,
    run_subentry_flow,
    set_cover,
    setup_count,
    setup_entry,
)


async def test_each_change_sets_the_entry_up_exactly_once(hass: HomeAssistant) -> None:
    """Create, reconfigure and remove: one set-up each, no more, no less."""
    entry = await setup_entry(hass)
    set_cover(hass, "cover.example_window")
    assert setup_count(hass) == 1

    group = await add_group(hass, entry, "South")
    assert setup_count(hass) == 2

    window = await add_window(
        hass, entry, "Example window", ["cover.example_window"], group.subentry_id
    )
    assert setup_count(hass) == 3

    # Reconfigure a subentry: a flow of three steps saves once, at its end.
    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_GROUP,
        [
            {"name": "South"},
            INHERIT_ALL_SWITCHES,
            {"open_in_morning": "inherit_on", "morning_position": 0, "expert": {}},
        ],
        reconfigure=group.subentry_id,
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert setup_count(hass) == 4
    # The reloaded window sees the group's new value: inheritance at runtime.
    state = hass.states.get("sensor.example_window_effective_morning_position")
    assert state is not None
    assert float(state.state) == 0

    # Reconfigure the window: title and data change together, still one set-up.
    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [
            {
                "name": "Renamed window",
                "covers": ["cover.example_window"],
                "group_id": group.subentry_id,
            },
            INHERIT_ALL_SWITCHES,
            {"open_in_morning": "inherit_on", "morning_position": 40, "expert": {}},
        ],
        reconfigure=window.subentry_id,
    )
    assert result["type"] is FlowResultType.ABORT
    assert setup_count(hass) == 5

    # Remove a subentry.
    hass.config_entries.async_remove_subentry(entry, window.subentry_id)
    await hass.async_block_till_done()
    assert setup_count(hass) == 6


async def test_reconfigure_of_the_house_sets_up_exactly_once(
    hass: HomeAssistant,
) -> None:
    """The reconfigure flow of the config entry itself follows the same rule."""
    entry = await setup_entry(hass)

    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "features"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "enable_daily_routine": True,
            "enable_shading": False,
            "enable_buttons": False,
        },
    )
    assert result["step_id"] == "feature_daily_routine"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "open_in_morning": True,
            "morning_position": 90,
            "evening_position": 0,
            "expert": {"random_offset": 0},
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_SETTINGS]["morning_position"] == 90
    assert setup_count(hass) == 2


async def test_reconfigure_without_a_change_does_not_reload(
    hass: HomeAssistant,
) -> None:
    """Home Assistant calls the listener only when something changed."""
    entry = await setup_entry(hass)
    group = await add_group(hass, entry, "South")
    assert setup_count(hass) == 2

    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_GROUP,
        [
            {"name": "South"},
            INHERIT_ALL_SWITCHES,
            {"open_in_morning": "inherit_on", "expert": {}},
        ],
        reconfigure=group.subentry_id,
    )

    assert result["type"] is FlowResultType.ABORT
    assert setup_count(hass) == 2


async def test_reloading_method_is_refused_while_a_listener_exists(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other combination is not just deprecated for subentries: it raises.

    ``ConfigSubentryFlow.async_update_reload_and_abort`` raises ``ValueError``
    when the entry has an update listener. The flow manager turns that into a
    failed flow, and nothing is reloaded twice.
    """
    entry = await setup_entry(hass)
    group = await add_group(hass, entry, "South")

    async def finish_with_reload(self: GroupSubentryFlow) -> object:
        return self.async_update_reload_and_abort(
            self._get_entry(),
            self._get_reconfigure_subentry(),
            data={CONF_SETTINGS: {"morning_position": 1}},
        )

    monkeypatch.setattr(GroupSubentryFlow, "_async_finish", finish_with_reload)

    with pytest.raises(ValueError, match="update listeners"):
        await run_subentry_flow(
            hass,
            entry,
            SUBENTRY_GROUP,
            [
                {"name": "South"},
                INHERIT_ALL_SWITCHES,
                {"open_in_morning": "inherit_on", "expert": {}},
            ],
            reconfigure=group.subentry_id,
        )
