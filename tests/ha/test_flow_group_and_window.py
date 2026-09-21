"""Groups and windows through the UI flows: create, reconfigure, remove, every error."""

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roller_shutter_suite.const import (
    CONF_COVERS,
    CONF_DRY_RUN,
    CONF_GROUP_ID,
    CONF_SETTINGS,
    SUBENTRY_GROUP,
    SUBENTRY_WINDOW,
)
from custom_components.roller_shutter_suite.core.settings import STORED_NONE
from tests.ha.helpers import (
    NO_STOP,
    OPEN_CLOSE_ONLY,
    add_group,
    add_window,
    configure_subentry_flow,
    marker_of,
    routine_inherit,
    run_subentry_flow,
    schema_keys,
    schema_of,
    set_cover,
    setup_entry,
    start_subentry_flow,
    subentry_data,
    submit_steps,
    suggested_value,
)

INHERIT = routine_inherit()


async def test_entry_group_and_two_windows_without_a_restart(
    hass: HomeAssistant,
) -> None:
    """Create a group and two windows, reconfigure each, remove each; the entry stays loaded."""
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
    assert set(entry.runtime_data.windows) == {left.subentry_id, right.subentry_id}

    # Reconfigure the group: a new name and an own value.
    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_GROUP,
        [
            {"name": "South side"},
            *routine_inherit({"schedule_workday_source_choice": "none"}),
        ],
        reconfigure=group.subentry_id,
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    group = entry.subentries[group.subentry_id]
    assert group.title == "South side"
    assert group.data == {CONF_SETTINGS: {"schedule_workday_source": STORED_NONE}}

    # Reconfigure a window: the form shows what is stored; change its name.
    result = await start_subentry_flow(
        hass, entry, SUBENTRY_WINDOW, reconfigure=left.subentry_id
    )
    assert suggested_value(marker_of(result, "name")) == "Left"
    assert suggested_value(marker_of(result, "covers")) == ["cover.example_left"]
    assert suggested_value(marker_of(result, "group_id")) == group.subentry_id
    result = await configure_subentry_flow(
        hass,
        result,
        {
            "name": "Left window",
            "covers": ["cover.example_left"],
            "group_id": group.subentry_id,
        },
    )
    result = await submit_steps(hass, result, INHERIT)
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[left.subentry_id].title == "Left window"
    assert entry.runtime_data.windows[left.subentry_id].title == "Left window"

    # Remove a window, then the group, then the other window.
    assert hass.config_entries.async_remove_subentry(entry, right.subentry_id)
    await hass.async_block_till_done()
    assert set(entry.runtime_data.windows) == {left.subentry_id}
    assert hass.config_entries.async_remove_subentry(entry, group.subentry_id)
    assert hass.config_entries.async_remove_subentry(entry, left.subentry_id)
    await hass.async_block_till_done()

    assert entry.subentries == {}
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.windows == {}


async def test_window_without_a_group_stores_no_group_key(hass: HomeAssistant) -> None:
    """An absent key is the only way to say "no group"; ``null`` is never written."""
    set_cover(hass, "cover.example_window")
    entry = await setup_entry(hass)
    await add_group(hass, entry, "South", *INHERIT)

    window = await add_window(
        hass, entry, "Kitchen", ["cover.example_window"], *INHERIT
    )

    assert window.data == {
        CONF_COVERS: ["cover.example_window"],
        CONF_SETTINGS: {},
        CONF_DRY_RUN: True,
    }
    assert CONF_GROUP_ID not in window.data
    assert None not in window.data.values()


async def test_window_form_offers_the_group_only_if_one_exists(
    hass: HomeAssistant,
) -> None:
    """A select without options is useless, so the field is left out."""
    entry = await setup_entry(hass)

    result = await start_subentry_flow(hass, entry, SUBENTRY_WINDOW)
    assert schema_keys(result) == ["name", "covers"]

    group = await add_group(hass, entry, "South", *INHERIT)
    result = await start_subentry_flow(hass, entry, SUBENTRY_WINDOW)
    assert schema_keys(result) == ["name", "covers", "group_id"]
    options = schema_of(result)["group_id"].config["options"]
    assert options == [{"value": group.subentry_id, "label": "South"}]


async def test_new_window_starts_in_dry_run_and_reconfigure_keeps_the_state(
    hass: HomeAssistant,
) -> None:
    """New windows are stored in dry-run; the form neither asks for it nor resets it."""
    set_cover(hass, "cover.example_window")
    entry = await setup_entry(hass)
    window = await add_window(
        hass, entry, "Kitchen", ["cover.example_window"], *INHERIT
    )
    assert window.data[CONF_DRY_RUN] is True
    assert entry.runtime_data.windows[window.subentry_id].dry_run is True

    # Somebody armed the window (the way to do that arrives with a later block).
    hass.config_entries.async_update_subentry(
        entry, window, data={**window.data, CONF_DRY_RUN: False}
    )
    await hass.async_block_till_done()
    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [{"name": "Kitchen", "covers": ["cover.example_window"]}, *INHERIT],
        reconfigure=window.subentry_id,
    )

    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[window.subentry_id].data[CONF_DRY_RUN] is False
    assert entry.runtime_data.windows[window.subentry_id].dry_run is False


async def test_cover_of_another_window_is_refused_with_an_explanation(
    hass: HomeAssistant,
) -> None:
    """The error names the cover and the window that has it; the input is kept."""
    set_cover(hass, "cover.example_shared")
    entry = await setup_entry(hass)
    await add_window(hass, entry, "Kitchen", ["cover.example_shared"], *INHERIT)

    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [{"name": "Dining room", "covers": ["cover.example_shared"]}],
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "basics"
    assert result["errors"] == {"covers": "cover_in_use"}
    assert result["description_placeholders"] == {
        "cover": "cover.example_shared",
        "window": "Kitchen",
    }
    assert suggested_value(marker_of(result, "name")) == "Dining room"
    assert [s.title for s in entry.subentries.values()] == ["Kitchen"]


async def test_window_may_keep_its_own_cover_on_reconfigure(
    hass: HomeAssistant,
) -> None:
    """The window's own subentry is left out of the comparison."""
    set_cover(hass, "cover.example_window")
    entry = await setup_entry(hass)
    window = await add_window(
        hass, entry, "Kitchen", ["cover.example_window"], *INHERIT
    )

    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [{"name": "Kitchen", "covers": ["cover.example_window"]}, *INHERIT],
        reconfigure=window.subentry_id,
    )

    assert result["reason"] == "reconfigure_successful"


async def test_cover_check_runs_again_right_before_saving(hass: HomeAssistant) -> None:
    """Two flows that are open at the same time cannot both take a cover."""
    set_cover(hass, "cover.example_shared")
    entry = await setup_entry(hass)
    basics: dict[str, Any] = {"covers": ["cover.example_shared"]}

    first = await run_subentry_flow(
        hass, entry, SUBENTRY_WINDOW, [{"name": "First"} | basics]
    )
    second = await run_subentry_flow(
        hass, entry, SUBENTRY_WINDOW, [{"name": "Second"} | basics]
    )
    assert first["step_id"] == second["step_id"] == "features"

    first = await submit_steps(hass, first, INHERIT)
    second = await submit_steps(hass, second, INHERIT)

    assert first["type"] is FlowResultType.CREATE_ENTRY
    assert second["type"] is FlowResultType.FORM
    assert second["step_id"] == "basics"
    assert second["errors"] == {"covers": "cover_in_use"}
    assert second["description_placeholders"]["window"] == "First"
    assert [s.title for s in entry.subentries.values()] == ["First"]


async def test_cover_group_is_taken_apart_shown_and_its_members_are_stored(
    hass: HomeAssistant,
) -> None:
    """A real cover group, and a group inside it, end as members in the stored data."""
    for cover in ("left", "right", "roof"):
        set_cover(hass, f"cover.example_{cover}")
    assert await async_setup_component(
        hass,
        "cover",
        {
            "cover": [
                {
                    "platform": "group",
                    "name": "Example inner",
                    "entities": ["cover.example_left", "cover.example_right"],
                },
                {
                    "platform": "group",
                    "name": "Example outer",
                    "entities": [
                        "cover.example_inner",
                        "cover.example_roof",
                        "cover.example_outer",
                    ],
                },
            ]
        },
    )
    await hass.async_block_till_done()
    entry = await setup_entry(hass)

    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [{"name": "Bay", "covers": ["cover.example_outer", "cover.example_left"]}],
    )

    # A menu before anything is saved: continue, or go back to the selection.
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "members"
    assert result["menu_options"] == ["members_accept", "basics"]
    assert result["description_placeholders"] == {
        "groups": "cover.example_outer, cover.example_inner",
        "members": "cover.example_left, cover.example_right, cover.example_roof",
    }

    back = await configure_subentry_flow(hass, result, {"next_step_id": "basics"})
    assert back["step_id"] == "basics"
    assert suggested_value(marker_of(back, "covers")) == [
        "cover.example_outer",
        "cover.example_left",
    ]

    result = await configure_subentry_flow(
        hass, back, {"name": "Bay", "covers": ["cover.example_outer"]}
    )
    result = await configure_subentry_flow(
        hass, result, {"next_step_id": "members_accept"}
    )
    result = await submit_steps(hass, result, INHERIT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_COVERS] == [
        "cover.example_left",
        "cover.example_right",
        "cover.example_roof",
    ]


async def test_group_with_a_member_of_another_window_is_refused(
    hass: HomeAssistant,
) -> None:
    """The explanation names the member, not the group."""
    set_cover(hass, "cover.example_left")
    hass.states.async_set(
        "cover.example_pair",
        "open",
        {"entity_id": ["cover.example_left", "cover.example_right"]},
    )
    entry = await setup_entry(hass)
    await add_window(hass, entry, "Kitchen", ["cover.example_left"], *INHERIT)

    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [{"name": "Pair", "covers": ["cover.example_pair"]}],
    )

    assert result["errors"] == {"covers": "cover_in_use"}
    assert result["description_placeholders"]["cover"] == "cover.example_left"


async def test_group_without_a_state_is_resolved_from_its_config_entry(
    hass: HomeAssistant,
) -> None:
    """While a group has no state, the registry and its config entry still answer."""
    set_cover(hass, "cover.example_left")
    group_entry = await setup_entry_of_group_platform(hass)
    er.async_get(hass).async_get_or_create(
        "cover",
        "group",
        "example_unique",
        suggested_object_id="example_stateless",
        config_entry=group_entry,
    )
    entry = await setup_entry(hass)

    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [{"name": "Stateless", "covers": ["cover.example_stateless"]}],
    )

    assert result["step_id"] == "members"
    assert result["description_placeholders"]["members"] == "cover.example_left"


async def setup_entry_of_group_platform(hass: HomeAssistant) -> MockConfigEntry:
    """Return a config entry as the group integration stores one; it is not set up."""
    group_entry = MockConfigEntry(
        domain="group",
        title="Example stateless",
        options={"entities": ["cover.example_left"], "group_type": "cover"},
    )
    group_entry.add_to_hass(hass)
    return group_entry


async def test_selection_without_a_cover_is_refused(hass: HomeAssistant) -> None:
    """A group that contains no cover leaves nothing to store."""
    hass.states.async_set(
        "cover.example_empty", "open", {"entity_id": ["light.example_lamp"]}
    )
    entry = await setup_entry(hass)

    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [{"name": "Empty", "covers": ["cover.example_empty"]}],
    )

    assert result["step_id"] == "basics"
    assert result["errors"] == {"covers": "no_covers"}


async def test_cover_without_position_feedback_is_accepted_and_explained(
    hass: HomeAssistant,
) -> None:
    """N2: the cover is not refused; a page says what will be inactive for it."""
    set_cover(hass, "cover.example_full")
    set_cover(hass, "cover.example_plain", OPEN_CLOSE_ONLY, position=None)
    entry = await setup_entry(hass)

    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [{"name": "Garage", "covers": ["cover.example_full", "cover.example_plain"]}],
    )

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "degraded"
    assert result["menu_options"] == ["degraded_accept", "basics"]
    assert result["description_placeholders"] == {"covers": "cover.example_plain"}

    result = await configure_subentry_flow(
        hass, result, {"next_step_id": "degraded_accept"}
    )
    result = await submit_steps(hass, result, INHERIT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    window = entry.runtime_data.windows[result_subentry_id(entry, "Garage")]
    config = window.resolution.config
    assert config is not None
    assert [member.capabilities.reports_position for member in config.members] == [
        True,
        False,
    ]


def result_subentry_id(entry: MockConfigEntry, title: str) -> str:
    """Return the ID of the subentry with the given title."""
    return next(s.subentry_id for s in entry.subentries.values() if s.title == title)


async def test_cover_with_positions_needs_no_explanation(hass: HomeAssistant) -> None:
    """A cover that lacks only "stop" still works with positions."""
    set_cover(hass, "cover.example_roof", NO_STOP)
    entry = await setup_entry(hass)

    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [{"name": "Roof", "covers": ["cover.example_roof"]}],
    )

    assert result["step_id"] == "features"


async def test_window_whose_covers_cannot_be_read_opens_with_an_empty_selection(
    hass: HomeAssistant,
) -> None:
    """The form of a faulty window starts from an empty field instead of failing."""
    set_cover(hass, "cover.example_window")
    entry = await setup_entry(
        hass,
        subentries=[
            subentry_data(
                SUBENTRY_WINDOW, "Broken", {CONF_COVERS: None}, "window_broken"
            )
        ],
    )

    result = await start_subentry_flow(
        hass, entry, SUBENTRY_WINDOW, reconfigure="window_broken"
    )
    assert suggested_value(marker_of(result, "covers")) == []

    result = await configure_subentry_flow(
        hass, result, {"name": "Repaired", "covers": ["cover.example_window"]}
    )
    result = await submit_steps(hass, result, INHERIT)

    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries["window_broken"].data == {
        CONF_COVERS: ["cover.example_window"],
        CONF_SETTINGS: {},
        CONF_DRY_RUN: True,
    }
    assert set(entry.runtime_data.windows) == {"window_broken"}
