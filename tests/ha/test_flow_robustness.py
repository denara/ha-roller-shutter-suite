"""What a flow took from an earlier page may be gone when it is used.

Home Assistant removes a subentry without asking, also while a flow is open
that refers to it. No flow may end in an exception because of that.
"""

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roller_shutter_suite.const import (
    CONF_COVERS,
    CONF_DRY_RUN,
    CONF_GROUP_ID,
    CONF_SETTINGS,
    SUBENTRY_GROUP,
    SUBENTRY_WINDOW,
)
from tests.ha.helpers import (
    add_group,
    add_window,
    configure_subentry_flow,
    marker_of,
    routine_inherit,
    schema_keys,
    set_cover,
    setup_entry,
    start_subentry_flow,
    submit_steps,
    suggested_value,
)

COVER = "cover.example_window"
INHERIT = routine_inherit()


async def _remove(
    hass: HomeAssistant, entry: MockConfigEntry, subentry_id: str
) -> None:
    assert hass.config_entries.async_remove_subentry(entry, subentry_id)
    await hass.async_block_till_done()


def _basics(group_id: str | None = None) -> dict[str, Any]:
    basics: dict[str, Any] = {"name": "Kitchen", "covers": [COVER]}
    if group_id is not None:
        basics["group_id"] = group_id
    return basics


async def test_group_removed_while_a_new_window_is_being_added(
    hass: HomeAssistant,
) -> None:
    """The flow goes on without the group, says so, and stores no group key."""
    set_cover(hass, COVER)
    entry = await setup_entry(hass)
    group = await add_group(hass, entry, "South", *INHERIT)
    result = await start_subentry_flow(hass, entry, SUBENTRY_WINDOW)
    assert "group_id" in schema_keys(result)

    # Removed while the first page is open: the page comes back with the hint.
    await _remove(hass, entry, group.subentry_id)
    result = await configure_subentry_flow(hass, result, _basics(group.subentry_id))

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "basics"
    assert result["errors"] == {"base": "group_removed"}
    assert "group_id" not in schema_keys(result)
    assert suggested_value(marker_of(result, "name")) == "Kitchen"

    result = await submit_steps(hass, result, [_basics(), *INHERIT])

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_COVERS: [COVER],
        CONF_SETTINGS: {},
        CONF_DRY_RUN: True,
    }
    assert not ir.async_get(hass).issues


async def test_group_removed_after_the_first_page_of_a_new_window(
    hass: HomeAssistant,
) -> None:
    """The group is looked at again right before saving; nothing dangling is stored."""
    set_cover(hass, COVER)
    entry = await setup_entry(hass)
    group = await add_group(hass, entry, "South", *INHERIT)
    other = await add_group(hass, entry, "North", *INHERIT)
    result = await start_subentry_flow(hass, entry, SUBENTRY_WINDOW)
    result = await configure_subentry_flow(hass, result, _basics(group.subentry_id))
    assert result["step_id"] == "features"

    await _remove(hass, entry, group.subentry_id)
    result = await submit_steps(hass, result, INHERIT)

    assert result["step_id"] == "basics"
    assert result["errors"] == {"base": "group_removed"}
    # The group that is left is still on offer; the removed one is not suggested.
    options = result["data_schema"].schema["group_id"].config["options"]
    assert [option["value"] for option in options] == [other.subentry_id]
    assert suggested_value(marker_of(result, "group_id")) is None

    result = await submit_steps(hass, result, [_basics(), *INHERIT])

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_GROUP_ID not in result["data"]


async def test_group_removed_while_a_window_is_being_changed(
    hass: HomeAssistant,
) -> None:
    """Reconfigure: the same hint, and saving stores the window without a group."""
    set_cover(hass, COVER)
    entry = await setup_entry(hass)
    group = await add_group(hass, entry, "South", *INHERIT)
    window = await add_window(
        hass, entry, "Kitchen", [COVER], *INHERIT, group_id=group.subentry_id
    )
    result = await start_subentry_flow(
        hass, entry, SUBENTRY_WINDOW, reconfigure=window.subentry_id
    )
    assert suggested_value(marker_of(result, "group_id")) == group.subentry_id

    await _remove(hass, entry, group.subentry_id)
    result = await configure_subentry_flow(hass, result, _basics(group.subentry_id))

    assert result["step_id"] == "basics"
    assert result["errors"] == {"base": "group_removed"}

    result = await submit_steps(hass, result, [_basics(), *INHERIT])

    assert result["reason"] == "reconfigure_successful"
    assert CONF_GROUP_ID not in entry.subentries[window.subentry_id].data
    # Saving repaired the reference, so the issue of the set-up is gone too.
    assert not ir.async_get(hass).issues


@pytest.mark.parametrize("removed_after_first_page", [False, True])
async def test_window_removed_while_it_is_being_changed(
    hass: HomeAssistant, removed_after_first_page: bool
) -> None:
    """The flow ends with a translated reason and saves nothing."""
    set_cover(hass, COVER)
    entry = await setup_entry(hass)
    window = await add_window(hass, entry, "Kitchen", [COVER], *INHERIT)
    result = await start_subentry_flow(
        hass, entry, SUBENTRY_WINDOW, reconfigure=window.subentry_id
    )
    inputs = [_basics(), *INHERIT]
    if removed_after_first_page:
        result = await configure_subentry_flow(hass, result, inputs.pop(0))

    await _remove(hass, entry, window.subentry_id)
    remaining = inputs if removed_after_first_page else inputs[:1]
    result = await submit_steps(hass, result, remaining)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "subentry_removed"
    assert entry.subentries == {}


@pytest.mark.parametrize("removed_after_first_page", [False, True])
async def test_group_removed_while_it_is_being_changed(
    hass: HomeAssistant, removed_after_first_page: bool
) -> None:
    """The same for a group."""
    entry = await setup_entry(hass)
    group = await add_group(hass, entry, "South", *INHERIT)
    result = await start_subentry_flow(
        hass, entry, SUBENTRY_GROUP, reconfigure=group.subentry_id
    )
    inputs = [{"name": "South"}, *INHERIT]
    if removed_after_first_page:
        result = await configure_subentry_flow(hass, result, inputs.pop(0))

    await _remove(hass, entry, group.subentry_id)
    remaining = inputs if removed_after_first_page else inputs[:1]
    result = await submit_steps(hass, result, remaining)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "subentry_removed"
    assert entry.subentries == {}


@pytest.mark.parametrize("subentry_type", [SUBENTRY_GROUP, SUBENTRY_WINDOW])
async def test_blank_name_is_refused(hass: HomeAssistant, subentry_type: str) -> None:
    """The name is the title of the subentry; issues and messages show it."""
    set_cover(hass, COVER)
    entry = await setup_entry(hass)
    result = await start_subentry_flow(hass, entry, subentry_type)
    basics = _basics() if subentry_type == SUBENTRY_WINDOW else {}

    result = await configure_subentry_flow(hass, result, basics | {"name": "   "})

    assert result["step_id"] == "basics"
    assert result["errors"] == {"name": "name_blank"}

    # Blanks around a name are not part of it.
    result = await submit_steps(
        hass, result, [basics | {"name": "  Kitchen "}, *INHERIT]
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert [subentry.title for subentry in entry.subentries.values()] == ["Kitchen"]
