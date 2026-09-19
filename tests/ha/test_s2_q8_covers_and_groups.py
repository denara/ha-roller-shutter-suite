"""SPIKE S2, question 8 and the resolution of Home Assistant cover groups."""

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roller_shutter_suite.const import CONF_COVERS, SUBENTRY_WINDOW
from custom_components.roller_shutter_suite.flow.covers import (
    group_members,
    resolve_covers,
)
from tests.ha.s2_helpers import (
    INHERIT_ALL_SWITCHES,
    add_window,
    marker_of,
    run_subentry_flow,
    set_cover,
    setup_count,
    setup_entry,
)

ROUTINE = {"open_in_morning": "inherit_on", "expert": {}}


async def add_cover_group(hass: HomeAssistant, name: str, members: list[str]) -> str:
    """Create a real cover group with Home Assistant's group integration."""
    group_entry = MockConfigEntry(
        domain="group",
        title=name,
        options={
            "group_type": "cover",
            "name": name,
            "entities": members,
            "hide_members": False,
        },
    )
    group_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(group_entry.entry_id)
    await hass.async_block_till_done()
    return f"cover.{name.lower().replace(' ', '_')}"


async def test_cover_of_another_window_is_refused_with_an_explanation(
    hass: HomeAssistant,
) -> None:
    """N3: the error names the cover and the window that owns it."""
    entry = await setup_entry(hass)
    set_cover(hass, "cover.example_window")
    set_cover(hass, "cover.example_other")
    await add_window(hass, entry, "First window", ["cover.example_window"])
    count = setup_count(hass)

    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [{"name": "Second window", "covers": ["cover.example_window"]}],
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "basics"
    assert result["errors"] == {"covers": "cover_in_use"}
    assert result["description_placeholders"] == {
        "cover": "cover.example_window",
        "window": "First window",
    }
    # The form keeps what the user typed, and nothing was saved or reloaded.
    assert marker_of(result, "name").description == {"suggested_value": "Second window"}
    assert len(entry.subentries) == 1
    assert setup_count(hass) == count

    # Correcting the selection in the same flow works.
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Second window", "covers": ["cover.example_other"]}
    )
    assert result["step_id"] == "features"


async def test_window_may_keep_its_own_cover_on_reconfigure(
    hass: HomeAssistant,
) -> None:
    """The uniqueness check ignores the window that is being changed."""
    entry = await setup_entry(hass)
    set_cover(hass, "cover.example_window")
    window = await add_window(hass, entry, "First window", ["cover.example_window"])

    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [{"name": "First window", "covers": ["cover.example_window"]}],
        reconfigure=window.subentry_id,
    )

    assert result["step_id"] == "features"


async def test_real_cover_group_is_recognized_and_resolved(hass: HomeAssistant) -> None:
    """A cover group of the group integration, and a group inside a group."""
    for member in ("cover.example_left", "cover.example_right", "cover.example_roof"):
        set_cover(hass, member)
    inner = await add_cover_group(
        hass, "Example pair", ["cover.example_left", "cover.example_right"]
    )
    outer = await add_cover_group(hass, "Example all", [inner, "cover.example_roof"])

    assert group_members(hass, "cover.example_left") is None
    assert group_members(hass, inner) == ["cover.example_left", "cover.example_right"]

    resolved = resolve_covers(hass, [outer, "cover.example_left"])
    assert resolved.members == [
        "cover.example_left",
        "cover.example_right",
        "cover.example_roof",
    ]
    assert resolved.groups == [outer, inner]


async def test_group_without_registry_entry_is_recognized_by_its_state(
    hass: HomeAssistant,
) -> None:
    """A cover group from YAML without unique ID has only its state attribute."""
    hass.states.async_set(
        "cover.example_yaml_group",
        "open",
        {"entity_id": ["cover.example_left", "cover.example_right"]},
    )

    assert group_members(hass, "cover.example_yaml_group") == [
        "cover.example_left",
        "cover.example_right",
    ]


async def test_group_without_state_is_resolved_from_its_config_entry(
    hass: HomeAssistant,
) -> None:
    """While the group has no state, the registry and its entry still answer."""
    for member in ("cover.example_left", "cover.example_right"):
        set_cover(hass, member)
    group = await add_cover_group(
        hass, "Example pair", ["cover.example_left", "cover.example_right"]
    )
    hass.states.async_remove(group)

    assert group_members(hass, group) == ["cover.example_left", "cover.example_right"]


async def test_members_are_shown_before_saving_and_stored_instead_of_the_group(
    hass: HomeAssistant,
) -> None:
    """The flow shows the resolved members, offers a way back, stores members."""
    entry = await setup_entry(hass)
    for member in ("cover.example_left", "cover.example_right"):
        set_cover(hass, member)
    group = await add_cover_group(
        hass, "Example pair", ["cover.example_left", "cover.example_right"]
    )

    result = await run_subentry_flow(
        hass, entry, SUBENTRY_WINDOW, [{"name": "Example window", "covers": [group]}]
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "members"
    assert result["menu_options"] == ["members_accept", "basics"]
    assert result["description_placeholders"] == {
        "groups": group,
        "members": "cover.example_left, cover.example_right",
    }

    # The way back shows the selection form again, pre-filled.
    back = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "basics"}
    )
    assert back["step_id"] == "basics"
    assert marker_of(back, "covers").description == {"suggested_value": [group]}

    result = await hass.config_entries.subentries.async_configure(
        back["flow_id"], {"name": "Example window", "covers": [group]}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"next_step_id": "members_accept"}
    )
    assert result["step_id"] == "features"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], INHERIT_ALL_SWITCHES
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], ROUTINE
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_COVERS] == ["cover.example_left", "cover.example_right"]


async def test_group_with_a_member_of_another_window_is_refused(
    hass: HomeAssistant,
) -> None:
    """The error names the member, not the group."""
    entry = await setup_entry(hass)
    for member in ("cover.example_left", "cover.example_right"):
        set_cover(hass, member)
    group = await add_cover_group(
        hass, "Example pair", ["cover.example_left", "cover.example_right"]
    )
    await add_window(hass, entry, "First window", ["cover.example_right"])

    result = await run_subentry_flow(
        hass, entry, SUBENTRY_WINDOW, [{"name": "Second window", "covers": [group]}]
    )

    assert result["errors"] == {"covers": "cover_in_use"}
    assert result["description_placeholders"] == {
        "cover": "cover.example_right",
        "window": "First window",
    }
