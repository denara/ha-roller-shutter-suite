"""The page of every cover of a window: what no entity can report about it.

One page per cover, after the feature pages (ruling 3 of the project owner
for block H10): the position source, the tolerance, the reporting kind and
time, and the travel times. What is stored holds only what differs; the
capability profile and the deadline read it.
"""

import json
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.selector import SelectSelector
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roller_shutter_suite import controller as controller_module
from custom_components.roller_shutter_suite.const import (
    CONF_MEMBERS,
    CONFIG_MINOR_VERSION,
    CONFIG_VERSION,
    SUBENTRY_WINDOW,
)
from custom_components.roller_shutter_suite.core.arbiter import member_expectation_end
from custom_components.roller_shutter_suite.core.model import (
    DEFAULT_TRAVEL_TIME,
    PositionSource,
    ReportingKind,
)
from custom_components.roller_shutter_suite.flow import member_page
from tests.ha.helpers import (
    MEMBER_PAGE,
    add_window,
    configure_subentry_flow,
    marker_of,
    page_as_shown,
    routine_inherit,
    schema_keys,
    schema_of,
    set_cover,
    setup_entry,
    start_subentry_flow,
    subentry_named,
    suggested_value,
)
from tests.ha.runtime_kit import (
    COVER,
    WINDOW_ID,
    controller_of,
    monday_morning,
    settle,
    setup_window,
    window_data,
)

_monday_morning = pytest.fixture(autouse=True)(monday_morning)

ROOT = Path(__file__).parents[2]
LEFT = "cover.example_left"
RIGHT = "cover.example_right"
NOTHING_STATED = {"position_source": "calculated", "reporting_kind": "not_stated"}
EVERYTHING = {
    "position_source": "measured",
    "tolerance": 4.0,
    "reporting_kind": "event_driven",
    "reporting_time": 30.0,
    "travel_time_up": 25.0,
    "travel_time_down": 22.0,
}


async def _to_the_member_pages(
    hass: HomeAssistant, covers: list[str], reconfigure: str | None = None
) -> tuple[Any, dict[str, Any]]:
    """Set the house up (unless it is) and walk a window flow to its first cover page."""
    for cover in covers:
        set_cover(hass, cover)
    entries = hass.config_entries.async_entries("roller_shutter_suite")
    entry = cast("MockConfigEntry", entries[0]) if entries else await setup_entry(hass)
    result = await start_subentry_flow(hass, entry, SUBENTRY_WINDOW, reconfigure)
    for user_input in [
        {"name": "Example window", "covers": covers},
        *routine_inherit(),
    ]:
        result = await configure_subentry_flow(hass, result, user_input)
    assert result["step_id"] == MEMBER_PAGE, result
    return entry, result


async def test_every_cover_gets_a_page_of_its_own_in_the_order_of_the_window(
    hass: HomeAssistant,
) -> None:
    """One page per cover, "Cover 1 of 2"; the last page of a new window submits."""
    _, result = await _to_the_member_pages(hass, [LEFT, RIGHT])

    assert schema_keys(result) == list(member_page.FIELDS)
    placeholders = result["description_placeholders"]
    assert (placeholders["member"], placeholders["member_number"]) == (LEFT, "1")
    assert placeholders["member_count"] == "2"
    assert result["last_step"] is False
    for choice in ("position_source", "reporting_kind"):
        selector = schema_of(result)[marker_of(result, choice)]
        assert isinstance(selector, SelectSelector)
        assert selector.config["translation_key"] == choice
    assert marker_of(result, "position_source").default() == "calculated"
    # No default for the reporting: it is not stated until the user states it.
    assert marker_of(result, "reporting_kind").default() == "not_stated"
    for number in ("tolerance", "reporting_time", "travel_time_up", "travel_time_down"):
        assert suggested_value(marker_of(result, number)) is None

    result = await configure_subentry_flow(hass, result, NOTHING_STATED)
    assert result["description_placeholders"]["member"] == RIGHT
    assert result["description_placeholders"]["member_number"] == "2"
    assert result["last_step"] is True
    result = await configure_subentry_flow(hass, result, NOTHING_STATED)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_the_ranges_and_defaults_of_the_registry_are_the_placeholders(
    hass: HomeAssistant,
) -> None:
    """Written once, in the registry: the page shows them, no text repeats them."""
    _, result = await _to_the_member_pages(hass, [COVER])
    placeholders = result["description_placeholders"]

    assert placeholders["tolerance_minimum"] == "1"
    assert placeholders["tolerance_maximum"] == "20 %"
    assert placeholders["tolerance_calculated"] == "2 %"
    assert placeholders["tolerance_measured"] == "3 %"
    assert placeholders["reporting_time_minimum"] == "0"
    assert placeholders["reporting_time_maximum"] == "600 s"
    assert placeholders["travel_time_up_default"] == "60 s"
    assert placeholders["travel_time_down_maximum"] == "600 s"
    box = schema_of(result)[marker_of(result, "reporting_time")]
    assert (box.config["min"], box.config["max"]) == (0, 600)
    assert box.config["unit_of_measurement"] == "s"


async def test_only_what_differs_is_stored_and_the_profile_reads_it(
    hass: HomeAssistant,
) -> None:
    """A cover that states nothing is not listed; defaults are not written."""
    entry, result = await _to_the_member_pages(hass, [LEFT, RIGHT])
    result = await configure_subentry_flow(hass, result, EVERYTHING)
    result = await configure_subentry_flow(
        hass,
        result,
        NOTHING_STATED | {"travel_time_up": 60.0, "travel_time_down": 60},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    window = subentry_named(entry, "Example window")
    assert window.data[CONF_MEMBERS] == {
        LEFT: {
            "position_source": "measured",
            "tolerance": 4,
            "reporting_kind": "event_driven",
            "reporting_time": 30,
            "travel_time_up": 25,
            "travel_time_down": 22,
        }
    }
    config = entry.runtime_data.runtime.windows[window.subentry_id].config
    left, right = config.members
    assert left.capabilities.position_source is PositionSource.MEASURED
    assert left.capabilities.tolerance == 4  # noqa: PLR2004
    assert left.capabilities.reporting_kind is ReportingKind.EVENT_DRIVEN
    assert left.capabilities.reporting_time == timedelta(seconds=30)
    assert left.capabilities.travel_time_up == timedelta(seconds=25)
    assert right.capabilities.reporting_kind is None
    assert right.capabilities.reporting_time is None
    assert right.capabilities.travel_time_down == DEFAULT_TRAVEL_TIME


async def test_a_window_whose_covers_state_nothing_stores_no_mapping(
    hass: HomeAssistant,
) -> None:
    """Section 9: members are listed only where they differ."""
    set_cover(hass, COVER)
    entry = await setup_entry(hass)
    window = await add_window(hass, entry, "Kitchen", [COVER], *routine_inherit())

    assert CONF_MEMBERS not in window.data


async def test_a_reconfigure_starts_from_what_the_cover_states_and_drops_a_fault(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Own values are suggested; a faulty stored value is not offered again."""
    members = {
        COVER: {
            "position_source": "measured",
            "reporting_kind": "polled",
            "reporting_time": 60,
            "tolerance": 50,
            "travel_time_down": 35,
        }
    }
    entry = await setup_window(
        hass, window_data(dry_run=True, members=members), freezer=freezer
    )
    profile = controller_of(entry).config.members[0].capabilities
    # The faulty tolerance reads as none stated: the default of the source.
    assert profile.tolerance == 3  # noqa: PLR2004
    assert profile.reporting_kind is ReportingKind.POLLED

    _, result = await _to_the_member_pages(hass, [COVER], reconfigure=WINDOW_ID)
    assert marker_of(result, "position_source").default() == "measured"
    assert marker_of(result, "reporting_kind").default() == "polled"
    assert suggested_value(marker_of(result, "reporting_time")) == 60  # noqa: PLR2004
    assert suggested_value(marker_of(result, "travel_time_down")) == 35  # noqa: PLR2004
    assert suggested_value(marker_of(result, "tolerance")) is None

    result = await configure_subentry_flow(hass, result, page_as_shown(result))
    assert result["step_id"] == "operation"
    result = await configure_subentry_flow(hass, result, {"operation": "dry_run"})
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[WINDOW_ID].data[CONF_MEMBERS] == {
        COVER: {
            "position_source": "measured",
            "reporting_kind": "polled",
            "reporting_time": 60,
            "travel_time_down": 35,
        }
    }


REFUSALS = [
    ("tolerance", 0, "out_of_range_tolerance"),
    ("tolerance", 21, "out_of_range_tolerance"),
    ("tolerance", 2.5, "fraction_not_allowed"),
    ("reporting_time", -1, "out_of_range_reporting_time"),
    ("reporting_time", 601, "out_of_range_reporting_time"),
    ("reporting_time", 1.5, "fraction_not_allowed"),
    ("travel_time_up", 0, "out_of_range_travel_time_up"),
    ("travel_time_down", 601.0, "out_of_range_travel_time_down"),
    ("travel_time_down", float("inf"), "invalid_value"),
    ("travel_time_up", "long", "invalid_value"),
    ("travel_time_up", True, "invalid_value"),
]


@pytest.mark.parametrize(("field", "value", "error"), REFUSALS)
async def test_the_page_refuses_with_a_translated_error_and_saves_nothing(
    hass: HomeAssistant, field: str, value: object, error: str
) -> None:
    """No selector judges first; the page answers with its own error key."""
    entry, result = await _to_the_member_pages(hass, [COVER])

    answer = await hass.config_entries.subentries.async_configure(
        result["flow_id"], NOTHING_STATED | {field: value}
    )

    assert answer["type"] is FlowResultType.FORM
    assert answer["step_id"] == MEMBER_PAGE
    assert answer["errors"] == {field: error}
    assert all(s.subentry_type != SUBENTRY_WINDOW for s in entry.subentries.values())
    for language in ("en", "de"):
        strings = json.loads(
            (
                ROOT
                / "custom_components"
                / "roller_shutter_suite"
                / "translations"
                / f"{language}.json"
            ).read_text(encoding="utf-8")
        )
        text = strings["config_subentries"]["window"]["error"][error]
        for name in ("minimum", "maximum"):
            if error.startswith("out_of_range_"):
                placeholder = f"{field}_{name}"
                assert f"{{{placeholder}}}" in text
                assert placeholder in (answer["description_placeholders"] or {})


async def test_an_empty_text_in_a_number_box_states_nothing(
    hass: HomeAssistant,
) -> None:
    """A browser that sends an emptied field as text: nothing is stored."""
    entry, result = await _to_the_member_pages(hass, [COVER])
    result = await configure_subentry_flow(
        hass, result, NOTHING_STATED | {"tolerance": " "}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_MEMBERS not in subentry_named(entry, "Example window").data


async def test_the_deadline_reads_the_travel_time_and_the_reporting_time(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The provisional 60 seconds are gone: the deadline takes what the page states."""
    set_cover(hass, COVER, position=50)
    members = {
        COVER: {
            "reporting_kind": "event_driven",
            "reporting_time": 20,
            "travel_time_up": 30,
        }
    }
    entry = await setup_window(
        hass, window_data(members=members), covers_present=False, freezer=freezer
    )
    controller = controller_of(entry)
    member = controller.config.members[0]
    command = controller.state.member_state(COVER).last_own_command
    assert command is not None

    # From 50 up to 100 is half the travel.
    assert member_expectation_end(member, command) == command.time + timedelta(
        seconds=20 + 10 + 30 * 0.5 * 1.5 + 5
    )
    assert not hasattr(controller_module, "PROVISIONAL_TRAVEL_TIME")


async def test_learning_the_capabilities_of_a_late_cover_keeps_what_it_states(
    hass: HomeAssistant, freezer: Any
) -> None:
    """A cover that was never seen at set-up keeps its stated values once it appears."""
    members = {COVER: {"reporting_kind": "event_driven", "reporting_time": 5}}
    entry = await setup_window(
        hass,
        window_data(dry_run=True, members=members),
        covers_present=False,
        freezer=freezer,
    )
    controller = controller_of(entry)
    assert controller.config.members[0].capabilities.capabilities_known is False

    set_cover(hass, COVER, position=100)
    await settle(hass, freezer)

    profile = controller.config.members[0].capabilities
    assert profile.capabilities_known is True
    assert profile.reporting_kind is ReportingKind.EVENT_DRIVEN
    assert profile.reporting_time == timedelta(seconds=5)


def test_the_stored_layout_is_version_1_3() -> None:
    """1.3 added the optional mapping of what the covers of a window state."""
    assert (CONFIG_VERSION, CONFIG_MINOR_VERSION) == (1, 3)
