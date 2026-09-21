"""The inheritance pattern of the forms, shown with the settings of the daily routine.

The forms are generated from the registry of the core and the form description
of the feature; no flow class knows a setting. The last tests use the second
catalog of ``helpers.py`` for the two things that have no real setting yet.
"""

import dataclasses
from typing import Any

import probatio
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    SelectSelector,
    TextSelector,
    TimeSelector,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roller_shutter_suite import features
from custom_components.roller_shutter_suite.const import (
    CONF_SETTINGS,
    SUBENTRY_GROUP,
    SUBENTRY_WINDOW,
)
from custom_components.roller_shutter_suite.core.settings import STORED_NONE, Level
from custom_components.roller_shutter_suite.features.daily_routine import (
    DAILY_ROUTINE,
)
from custom_components.roller_shutter_suite.flow import inheritance
from custom_components.roller_shutter_suite.flow.model import (
    Catalog,
    FeatureForm,
    FieldForm,
    LevelContext,
    StepForm,
)
from tests.ha.helpers import (
    DAY_TYPES,
    GENERAL_INHERIT,
    NO_STOP,
    SWITCHES_INHERIT,
    add_group,
    add_window,
    configure_subentry_flow,
    day_inherit,
    marker_of,
    routine_inherit,
    run_subentry_flow,
    schema_keys,
    schema_of,
    section_marker_of,
    set_cover,
    setup_entry,
    subentry_data,
    submit_steps,
    suggested_value,
)

COVER = "cover.example_window"
HOUSE_POSITION = 60
GROUP_POSITION = 40
DELAY_MINUTES = 15
DEFAULT_DELAY = "10 min"
WORKDAY_PAGE = "feature_daily_routine_workday"
GENERAL_PAGE = "feature_daily_routine_general"


async def _house(hass: HomeAssistant, **settings: Any) -> MockConfigEntry:
    set_cover(hass, COVER)
    return await setup_entry(hass, {CONF_SETTINGS: settings})


def _rest_after(
    page: str, general: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Return the unchanged inputs of the pages that follow the given one."""
    inputs = routine_inherit(general)[1:]
    pages = [GENERAL_PAGE, *(f"feature_daily_routine_{day}" for day in DAY_TYPES)]
    return inputs[pages.index(page) + 1 :]


async def _window_page(  # noqa: PLR0913 - the ways a window flow can start
    hass: HomeAssistant,
    entry: MockConfigEntry,
    page: str = GENERAL_PAGE,
    *,
    reconfigure: str | None = None,
    group_id: str | None = None,
    covers: tuple[str, ...] = (COVER,),
    general: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Walk a window flow up to a page of the daily routine, changing nothing."""
    basics: dict[str, Any] = {"name": "Kitchen", "covers": list(covers)}
    if group_id is not None:
        basics["group_id"] = group_id
    inputs = routine_inherit(general)
    pages = [GENERAL_PAGE, *(f"feature_daily_routine_{day}" for day in DAY_TYPES)]
    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [basics, *inputs[: pages.index(page) + 1]],
        reconfigure,
    )
    assert result["step_id"] == page, result
    return result


async def _save_general(
    hass: HomeAssistant,
    result: dict[str, Any],
    changes: dict[str, Any],
    general: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit the general page with changes and every later page unchanged."""
    return await submit_steps(
        hass,
        result,
        [GENERAL_INHERIT | (general or {}) | changes, *_rest_after(GENERAL_PAGE)],
    )


def _own(entry: MockConfigEntry, subentry_id: str) -> dict[str, Any]:
    return dict(entry.subentries[subentry_id].data[CONF_SETTINGS])


async def test_boolean_is_overridden_and_returned_to_inherit(
    hass: HomeAssistant,
) -> None:
    """A switch is a drop-down "inherit / on / off"; "inherit" leaves no key behind."""
    entry = await _house(hass)
    window = await add_window(
        hass,
        entry,
        "Kitchen",
        [COVER],
        *routine_inherit({"schedule_summer_by_date": "on"}),
    )
    assert window.data[CONF_SETTINGS] == {"schedule_summer_by_date": True}

    result = await _window_page(
        hass,
        entry,
        reconfigure=window.subentry_id,
    )
    assert marker_of(result, "schedule_summer_by_date").default() == "on"
    # Exactly one inherit entry is offered: the one that names the inherited state.
    selector = schema_of(result)["schedule_summer_by_date"]
    assert isinstance(selector, SelectSelector)
    assert selector.config["options"] == ["inherit_off", "on", "off"]
    assert selector.config["translation_key"] == "inherited_switch"

    result = await _save_general(hass, result, {})

    assert result["reason"] == "reconfigure_successful"
    assert _own(entry, window.subentry_id) == {}


async def test_inherit_entry_of_a_boolean_follows_the_group(
    hass: HomeAssistant,
) -> None:
    """The inherit entry names what the level above yields at present."""
    entry = await _house(hass)
    group = await add_group(
        hass, entry, "South", *routine_inherit({"schedule_summer_by_date": "on"})
    )

    result = await _window_page(hass, entry, group_id=group.subentry_id)

    selector = schema_of(result)["schedule_summer_by_date"]
    assert selector.config["options"] == ["inherit_on", "on", "off"]
    assert marker_of(result, "schedule_summer_by_date").default() == "inherit_on"
    assert result["description_placeholders"]["schedule_summer_by_date_source"] == (
        "South"
    )


async def test_number_zero_is_an_own_value_and_empty_means_inherit(
    hass: HomeAssistant,
) -> None:
    """Only the absent key means "inherit"; zero is a value like any other."""
    entry = await _house(hass, schedule_morning_position=HOUSE_POSITION)
    window = await add_window(
        hass,
        entry,
        "Kitchen",
        [COVER],
        *routine_inherit({"schedule_morning_position": 0.0}),
    )
    stored = window.data[CONF_SETTINGS]
    assert stored == {"schedule_morning_position": 0}
    assert type(stored["schedule_morning_position"]) is int
    resolved = entry.runtime_data.windows[window.subentry_id].resolution
    assert resolved.config is not None
    assert resolved.config.schedule_morning_position.value == 0

    result = await _window_page(hass, entry, reconfigure=window.subentry_id)
    marker = marker_of(result, "schedule_morning_position")
    # The own value is suggested, never the default: a default would come
    # back when the field is emptied.
    assert suggested_value(marker) == 0
    assert marker.default is probatio.UNDEFINED
    assert isinstance(schema_of(result)["schedule_morning_position"], NumberSelector)
    placeholders = result["description_placeholders"]
    assert placeholders["schedule_morning_position_inherited"] == "60 %"
    assert placeholders["schedule_morning_position_source"] == entry.title

    # An emptied number field sends no key at all.
    result = await _save_general(hass, result, {})

    assert result["reason"] == "reconfigure_successful"
    assert _own(entry, window.subentry_id) == {}


@pytest.mark.parametrize(
    ("sent", "stored"),
    [(0.0, 0), (80.0, 80), (80, 80)],
    ids=["zero", "whole float", "integer"],
)
async def test_whole_number_is_stored_as_an_integer(
    hass: HomeAssistant, sent: float, stored: int
) -> None:
    """The number selector delivers floats; a whole-number setting stores an int."""
    entry = await _house(hass)

    window = await add_window(
        hass,
        entry,
        "Kitchen",
        [COVER],
        *routine_inherit({"schedule_evening_position": sent}),
    )

    value = window.data[CONF_SETTINGS]["schedule_evening_position"]
    assert value == stored
    assert type(value) is int


async def test_fraction_is_refused_for_a_whole_number_setting(
    hass: HomeAssistant,
) -> None:
    """80.5 is no position; the form says that a whole number is needed."""
    entry = await _house(hass)
    result = await _window_page(hass, entry)

    result = await configure_subentry_flow(
        hass, result, GENERAL_INHERIT | {"schedule_morning_position": 80.5}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == GENERAL_PAGE
    assert result["errors"] == {"schedule_morning_position": "fraction_not_allowed"}
    assert entry.subentries == {}


async def test_fraction_is_kept_for_a_setting_that_takes_one(
    hass: HomeAssistant,
) -> None:
    """Whether a fraction is fine is decided by the reader of the setting in the core."""
    entry = await _house(hass)

    window = await add_window(
        hass,
        entry,
        "Kitchen",
        [COVER],
        *routine_inherit({"schedule_brightness_threshold_lux": 22.5}),
    )

    # The form names the unit; the stored key is the key of the registry.
    assert window.data[CONF_SETTINGS] == {"schedule_brightness_threshold": 22.5}
    result = await _window_page(hass, entry, reconfigure=window.subentry_id)
    marker = marker_of(result, "schedule_brightness_threshold_lux")
    assert suggested_value(marker) == 22.5  # noqa: PLR2004 - the value from above
    selector = schema_of(result)["schedule_brightness_threshold_lux"]
    assert selector.config["unit_of_measurement"] == "lx"


async def test_number_that_is_not_finite_is_an_invalid_value(
    hass: HomeAssistant,
) -> None:
    """Infinity is no value of any setting, whatever a reader would say."""
    entry = await _house(hass)
    result = await _window_page(hass, entry)

    result = await configure_subentry_flow(
        hass,
        result,
        GENERAL_INHERIT | {"schedule_brightness_threshold_lux": float("inf")},
    )

    assert result["errors"] == {"schedule_brightness_threshold_lux": "invalid_value"}


async def test_value_the_core_refuses_is_a_form_error(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The value rules live in the core; a form whose bound is too wide still cannot save."""
    general, *days = DAILY_ROUTINE.steps
    too_wide = tuple(
        dataclasses.replace(item, maximum=60)
        if item.key == "schedule_random_offset"
        else item
        for item in general.fields
    )
    catalog = Catalog(
        registry=features.CATALOG.registry,
        features=(
            FeatureForm(
                DAILY_ROUTINE.feature_id,
                (StepForm(general.name, too_wide), *days),
                DAILY_ROUTINE.switch,
            ),
        ),
        resolve=features.CATALOG.resolve,
    )
    monkeypatch.setattr(features, "CATALOG", catalog)
    entry = await _house(hass)
    result = await _window_page(hass, entry)

    # The core allows a random offset of at most 30 minutes.
    result = await configure_subentry_flow(
        hass, result, GENERAL_INHERIT | {"expert": {"schedule_random_offset": 45}}
    )

    # A section shows no field errors, so an expert value reports on the form.
    assert result["errors"] == {"base": "invalid_value"}


async def test_combination_the_core_refuses_is_shown_on_the_fields_concerned(
    hass: HomeAssistant,
) -> None:
    """Each value alone is fine; together the core refuses them, before anything is saved."""
    entry = await _house(hass)
    result = await _window_page(hass, entry, WORKDAY_PAGE)

    # A morning at 21:00 lies after the earliest evening (not before 17:00).
    result = await configure_subentry_flow(
        hass,
        result,
        day_inherit("workday", schedule_workday_morning_time="21:00:00"),
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == WORKDAY_PAGE
    assert result["errors"] == {
        "schedule_workday_morning_time": "invalid_combination",
        "base": "invalid_combination",
    }
    named = result["description_placeholders"]["combination"].split(", ")
    assert "schedule_workday_morning_time" in named
    assert entry.subentries == {}

    # Corrected, the flow goes on.
    result = await configure_subentry_flow(
        hass,
        result,
        day_inherit("workday", schedule_workday_morning_time="06:15:00"),
    )
    assert result["step_id"] == "feature_daily_routine_weekend"


async def test_combination_of_expert_values_is_reported_on_the_form(
    hass: HomeAssistant,
) -> None:
    """Both clamps sit in the section, so their contradiction is reported on the form."""
    entry = await _house(hass)
    result = await _window_page(hass, entry, WORKDAY_PAGE)

    result = await configure_subentry_flow(
        hass,
        result,
        day_inherit(
            "workday",
            expert={
                "schedule_workday_evening_not_before": "22:30:00",
                "schedule_workday_evening_not_after": "21:00:00",
            },
        ),
    )

    assert result["errors"] == {"base": "invalid_combination"}
    assert result["description_placeholders"]["combination"] == (
        "schedule_workday_evening_not_after, schedule_workday_evening_not_before"
    )


async def test_optional_reference_has_three_choices(hass: HomeAssistant) -> None:
    """Inherit leaves no key, "none" stores the marker of the core, own stores the entity."""
    entry = await _house(hass, schedule_workday_source="binary_sensor.example_house")
    inherit = {"schedule_workday_source_choice": "inherit_reference"}
    result = await _window_page(hass, entry, general=inherit)

    choice = schema_of(result)["schedule_workday_source_choice"]
    assert choice.config["options"] == ["inherit_reference", "none", "own"]
    assert choice.config["translation_key"] == "reference_choice"
    placeholders = result["description_placeholders"]
    assert placeholders["schedule_workday_source_inherited"] == (
        "binary_sensor.example_house"
    )

    # Inherit: an entity left in the field is ignored.
    left_over = {"schedule_workday_source": "binary_sensor.example_ignored"}
    result = await _save_general(hass, result, left_over, inherit)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    window_id = next(iter(entry.subentries))
    assert _own(entry, window_id) == {}

    # None: also with an entity left in the field.
    result = await _window_page(hass, entry, reconfigure=window_id, general=inherit)
    result = await _save_general(
        hass, result, {"schedule_workday_source_choice": "none"} | left_over
    )
    assert _own(entry, window_id) == {"schedule_workday_source": STORED_NONE}
    resolved = entry.runtime_data.windows[window_id].resolution.settings
    assert resolved.values["schedule_workday_source"].value is None

    # The form shows "none" and suggests no entity; then: own selection.
    none = {"schedule_workday_source_choice": "none"}
    result = await _window_page(hass, entry, reconfigure=window_id, general=none)
    assert marker_of(result, "schedule_workday_source_choice").default() == "none"
    assert suggested_value(marker_of(result, "schedule_workday_source")) is None
    own = {
        "schedule_workday_source_choice": "own",
        "schedule_workday_source": "binary_sensor.example_own",
    }
    result = await _save_general(hass, result, own)
    assert _own(entry, window_id) == {
        "schedule_workday_source": "binary_sensor.example_own"
    }

    # Back from an own selection to "inherit", with the entity still in the field.
    result = await _window_page(hass, entry, reconfigure=window_id, general=own)
    assert marker_of(result, "schedule_workday_source_choice").default() == "own"
    assert suggested_value(marker_of(result, "schedule_workday_source")) == (
        "binary_sensor.example_own"
    )
    result = await _save_general(
        hass,
        result,
        inherit | {"schedule_workday_source": "binary_sensor.example_own"},
    )
    assert _own(entry, window_id) == {}


async def test_return_from_none_to_inherit(hass: HomeAssistant) -> None:
    """The marker for "none" does not survive the choice "inherit"."""
    entry = await _house(hass)
    none = {"schedule_holiday_source_choice": "none"}
    window = await add_window(hass, entry, "Kitchen", [COVER], *routine_inherit(none))
    assert window.data[CONF_SETTINGS] == {"schedule_holiday_source": STORED_NONE}

    result = await _window_page(
        hass, entry, reconfigure=window.subentry_id, general=none
    )
    # The house sets no source, so the inherit entry says "none".
    choice = schema_of(result)["schedule_holiday_source_choice"]
    assert choice.config["options"][0] == "inherit_none"
    assert result["description_placeholders"]["schedule_holiday_source_inherited"] == (
        "-"
    )
    result = await _save_general(hass, result, {})

    assert _own(entry, window.subentry_id) == {}


async def test_own_selection_without_an_entity_is_refused(hass: HomeAssistant) -> None:
    """An own selection needs an entity; the error stands at the entity field."""
    entry = await _house(hass)
    result = await _window_page(hass, entry)

    result = await configure_subentry_flow(
        hass, result, GENERAL_INHERIT | {"schedule_season_source_choice": "own"}
    )

    assert result["errors"] == {"schedule_season_source": "reference_missing"}


async def test_time_duration_and_day_of_year_come_from_registry_and_form_data(
    hass: HomeAssistant,
) -> None:
    """The kinds of the schedule settings work without a line in any flow class."""
    entry = await _house(hass)
    result = await _window_page(hass, entry)

    schema = schema_of(result)
    assert isinstance(schema["schedule_summer_first_day"], TextSelector)
    assert "schedule_brightness_delay" not in schema_keys(result)
    expert = schema["expert"].schema.schema
    assert isinstance(expert["schedule_brightness_delay"], NumberSelector)
    assert expert["schedule_brightness_delay"].config["unit_of_measurement"] == "min"
    placeholders = result["description_placeholders"]
    assert placeholders["schedule_summer_first_day_inherited"] == "05-01"
    assert placeholders["schedule_brightness_delay_inherited"] == DEFAULT_DELAY

    result = await configure_subentry_flow(
        hass,
        result,
        GENERAL_INHERIT
        | {
            "schedule_summer_first_day": "04-15",
            "expert": {"schedule_brightness_delay": float(DELAY_MINUTES)},
        },
    )
    assert result["step_id"] == WORKDAY_PAGE
    assert isinstance(schema_of(result)["schedule_workday_morning_time"], TimeSelector)
    expert = schema_of(result)["expert"].schema.schema
    assert isinstance(expert["schedule_workday_morning_not_after"], TimeSelector)
    placeholders = result["description_placeholders"]
    assert placeholders["schedule_workday_morning_time_inherited"] == "07:00:00"

    result = await submit_steps(
        hass,
        result,
        [
            day_inherit("workday", schedule_workday_morning_time="06:30:00"),
            *_rest_after(WORKDAY_PAGE),
        ],
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    window_id = next(iter(entry.subentries))
    # A duration is entered in its unit and stored in whole seconds.
    assert _own(entry, window_id) == {
        "schedule_summer_first_day": "04-15",
        "schedule_brightness_delay": DELAY_MINUTES * 60,
        "schedule_workday_morning_time": "06:30:00",
    }
    assert not entry.runtime_data.windows[window_id].resolution.settings.faults

    # The own values come back as suggestions, the duration in its unit.
    result = await _window_page(hass, entry, reconfigure=window_id)
    assert suggested_value(marker_of(result, "schedule_summer_first_day")) == "04-15"
    delay = section_marker_of(result, "expert", "schedule_brightness_delay")
    assert suggested_value(delay) == DELAY_MINUTES

    # Emptied fields: a text field may arrive as an empty text; both mean inherit.
    result = await configure_subentry_flow(
        hass, result, GENERAL_INHERIT | {"schedule_summer_first_day": " "}
    )
    marker = marker_of(result, "schedule_workday_morning_time")
    assert suggested_value(marker) == "06:30:00"
    result = await submit_steps(
        hass, result, [day_inherit("workday"), *_rest_after(WORKDAY_PAGE)]
    )
    assert _own(entry, window_id) == {}


@pytest.mark.parametrize(
    ("day", "error"),
    [("02-29", "leap_day_not_allowed"), ("1.5.", "invalid_day_of_year")],
    ids=["leap day", "wrong form"],
)
async def test_day_of_year_the_core_refuses_has_its_own_message(
    hass: HomeAssistant, day: str, error: str
) -> None:
    """29 February is refused by the reader of the core and explained on its own."""
    entry = await _house(hass)
    result = await _window_page(hass, entry)

    result = await configure_subentry_flow(
        hass, result, GENERAL_INHERIT | {"schedule_summer_last_day": day}
    )

    assert result["errors"] == {"schedule_summer_last_day": error}


async def test_fraction_of_a_duration_is_refused(hass: HomeAssistant) -> None:
    """A duration is a whole number of its unit."""
    entry = await _house(hass)
    result = await _window_page(hass, entry)

    result = await configure_subentry_flow(
        hass, result, GENERAL_INHERIT | {"expert": {"schedule_random_offset": 1.5}}
    )

    assert result["errors"] == {"base": "fraction_not_allowed"}


async def test_enumeration_has_an_inherit_entry(hass: HomeAssistant) -> None:
    """A choice is a drop-down of the values of the registry plus "inherit"."""
    entry = await _house(hass, schedule_workday_morning_kind="elevation")
    result = await _window_page(hass, entry, WORKDAY_PAGE)

    selector = schema_of(result)["schedule_workday_morning_kind"]
    assert selector.config["options"] == [
        "inherit",
        "fixed_time",
        "sun_event",
        "elevation",
    ]
    # The six trigger kinds offer the same choice and share its translation.
    assert selector.config["translation_key"] == "schedule_trigger_kind"
    placeholders = result["description_placeholders"]
    assert placeholders["schedule_workday_morning_kind_inherited"] == "elevation"

    result = await submit_steps(
        hass,
        result,
        [
            day_inherit("workday", schedule_workday_morning_kind="sun_event"),
            *_rest_after(WORKDAY_PAGE),
        ],
    )
    window_id = next(iter(entry.subentries))
    assert _own(entry, window_id) == {"schedule_workday_morning_kind": "sun_event"}

    result = await _window_page(hass, entry, WORKDAY_PAGE, reconfigure=window_id)
    assert marker_of(result, "schedule_workday_morning_kind").default() == "sun_event"


async def test_value_is_inherited_over_two_levels_and_names_its_source(
    hass: HomeAssistant,
) -> None:
    """House, group, window: the helper text names the level a value comes from."""
    entry = await _house(
        hass, schedule_morning_position=HOUSE_POSITION, schedule_evening_position=10
    )
    group = await add_group(
        hass,
        entry,
        "South",
        *routine_inherit({"schedule_morning_position": GROUP_POSITION}),
    )

    result = await _window_page(hass, entry, group_id=group.subentry_id)

    placeholders = result["description_placeholders"]
    assert placeholders["schedule_morning_position_inherited"] == "40 %"
    assert placeholders["schedule_morning_position_source"] == "South"
    assert placeholders["schedule_evening_position_inherited"] == "10 %"
    assert placeholders["schedule_evening_position_source"] == entry.title

    result = await _save_general(hass, result, {})
    window_id = next(s for s in entry.subentries if s != group.subentry_id)
    values = entry.runtime_data.windows[window_id].resolution.settings.values
    assert values["schedule_morning_position"].value.value == GROUP_POSITION
    assert values["schedule_morning_position"].group_id == group.subentry_id


async def test_only_features_that_are_switched_on_get_their_pages(
    hass: HomeAssistant,
) -> None:
    """Progressive configuration: a feature that is off, own or inherited, has no page."""
    entry = await _house(hass)

    # Switched off by the group itself: the flow ends after the switches.
    result = await run_subentry_flow(
        hass, entry, SUBENTRY_GROUP, [{"name": "North"}, {"schedule_enabled": "off"}]
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    group_id = next(iter(entry.subentries))
    assert entry.subentries[group_id].data == {
        CONF_SETTINGS: {"schedule_enabled": False}
    }

    # Inherited as off by a window of that group: no page either.
    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [
            {"name": "Kitchen", "covers": [COVER], "group_id": group_id},
            {"schedule_enabled": "inherit_off"},
        ],
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    # Switched on again by another window: the pages are back.
    set_cover(hass, "cover.example_other")
    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [
            {"name": "Hall", "covers": ["cover.example_other"], "group_id": group_id},
            {"schedule_enabled": "on"},
        ],
    )
    assert result["step_id"] == GENERAL_PAGE


async def test_values_of_pages_that_are_not_shown_stay_stored(
    hass: HomeAssistant,
) -> None:
    """Switching a feature off does not throw away what was set for it."""
    entry = await _house(hass)
    window = await add_window(
        hass,
        entry,
        "Kitchen",
        [COVER],
        *routine_inherit({"schedule_morning_position": GROUP_POSITION}),
    )

    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [{"name": "Kitchen", "covers": [COVER]}, {"schedule_enabled": "off"}],
        reconfigure=window.subentry_id,
    )

    assert result["reason"] == "reconfigure_successful"
    assert _own(entry, window.subentry_id) == {
        "schedule_enabled": False,
        "schedule_morning_position": GROUP_POSITION,
    }


async def test_form_judges_its_own_page_and_level_only(hass: HomeAssistant) -> None:
    """A fault of the house, or of a value of another page, does not block a page."""
    set_cover(hass, COVER)
    entry = await setup_entry(
        hass,
        {CONF_SETTINGS: {"schedule_summer_by_date": "yes"}},
        subentries=[
            subentry_data(
                SUBENTRY_WINDOW,
                "Kitchen",
                # The reader accepts 3600 seconds; the value rules refuse them.
                {"covers": [COVER], CONF_SETTINGS: {"schedule_random_offset": 3600}},
                "w1",
            )
        ],
    )

    # The page of the switches passes, although the window holds a value that
    # its own page will have to correct, and the house a faulty one.
    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [{"name": "Kitchen", "covers": [COVER]}, SWITCHES_INHERIT],
        reconfigure="w1",
    )
    assert result["step_id"] == GENERAL_PAGE

    result = await _save_general(hass, result, {})
    assert result["reason"] == "reconfigure_successful"
    assert _own(entry, "w1") == {}


@pytest.mark.usefixtures("example_catalog")
async def test_option_the_covers_cannot_do_is_replaced_by_a_read_only_reason(
    hass: HomeAssistant,
) -> None:
    """The stand-in names the limiting member, stores nothing and keeps the own value."""
    set_cover(hass, "cover.example_roof", NO_STOP)
    entry = await _house(hass)
    # The own value was stored while the cover could still stop.
    window = await add_window(
        hass, entry, "Kitchen", [COVER], *routine_inherit({"example_hold": "on"})
    )

    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [
            {"name": "Kitchen", "covers": [COVER, "cover.example_roof"]},
            SWITCHES_INHERIT,
        ],
        reconfigure=window.subentry_id,
    )

    keys = schema_keys(result)
    assert "example_hold" not in keys
    assert "example_hold_unavailable" in keys
    assert keys.index("example_hold_unavailable") < keys.index("expert")
    stand_in = schema_of(result)["example_hold_unavailable"]
    assert isinstance(stand_in, BooleanSelector)
    assert stand_in.config["read_only"] is True
    placeholders = result["description_placeholders"]
    assert placeholders["limited_by_supports_stop"] == "cover.example_roof"
    assert "example_hold_inherited" not in placeholders

    # A client that submits the stand-in smuggles nothing in; the schema does
    # not even know the field that the stand-in replaces.
    result = await _save_general(hass, result, {"example_hold_unavailable": True})

    assert result["reason"] == "reconfigure_successful"
    # The own value stays stored and applies again once the capability is back.
    assert _own(entry, window.subentry_id) == {"example_hold": True}
    resolved = entry.runtime_data.windows[window.subentry_id].resolution.settings
    assert resolved.values["example_hold"].effective is False
    assert [item.key for item in resolved.masked_own_values] == ["example_hold"]


@pytest.mark.usefixtures("example_catalog")
async def test_cover_that_was_never_seen_masks_nothing_and_reports_nothing(
    hass: HomeAssistant,
) -> None:
    """Capability state "unknown": the option is offered, and no repair issue appears."""
    entry = await setup_entry(hass)

    window = await add_window(
        hass,
        entry,
        "Kitchen",
        ["cover.example_never_seen"],
        SWITCHES_INHERIT,
        GENERAL_INHERIT | {"example_hold": "on"},
        *_rest_after(GENERAL_PAGE),
    )

    assert _own(entry, window.subentry_id) == {"example_hold": True}
    resolved = entry.runtime_data.windows[window.subentry_id].resolution.settings
    assert resolved.values["example_hold"].effective is True
    assert resolved.masked_own_values == ()
    assert not ir.async_get(hass).issues

    result = await _window_page(
        hass,
        entry,
        reconfigure=window.subentry_id,
        covers=("cover.example_never_seen",),
    )
    assert "example_hold" in schema_keys(result)
    assert "example_hold_unavailable" not in schema_keys(result)


@pytest.mark.usefixtures("example_catalog")
async def test_setting_that_is_not_inherited_is_offered_to_a_window_only(
    hass: HomeAssistant,
) -> None:
    """The registry says what can be inherited; the forms follow it."""
    entry = await _house(hass)

    group_page = await run_subentry_flow(
        hass, entry, SUBENTRY_GROUP, [{"name": "South"}, SWITCHES_INHERIT]
    )
    window_page = await _window_page(hass, entry)

    assert "example_window_only" not in schema_keys(group_page)
    assert "example_window_only" in schema_keys(window_page)


async def test_feature_without_a_switch_is_always_on(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without any switch there is no page of switches, and the pages always appear."""
    catalog = Catalog(
        registry=features.CATALOG.registry,
        features=(FeatureForm(DAILY_ROUTINE.feature_id, DAILY_ROUTINE.steps),),
        resolve=features.CATALOG.resolve,
    )
    monkeypatch.setattr(features, "CATALOG", catalog)
    entry = await _house(hass, schedule_enabled=False)

    result = await run_subentry_flow(
        hass, entry, SUBENTRY_WINDOW, [{"name": "Kitchen", "covers": [COVER]}]
    )

    assert result["step_id"] == GENERAL_PAGE


async def test_combination_is_reported_on_the_page_it_concerns(
    hass: HomeAssistant,
) -> None:
    """Stored values that clash do not block an earlier page; their own page reports them."""
    set_cover(hass, COVER)
    entry = await setup_entry(
        hass,
        subentries=[
            subentry_data(
                SUBENTRY_WINDOW,
                "Kitchen",
                {
                    "covers": [COVER],
                    CONF_SETTINGS: {"schedule_workday_morning_time": "21:00:00"},
                },
                "w1",
            )
        ],
    )

    # The general page has nothing to do with it and lets the user pass.
    result = await _window_page(hass, entry, WORKDAY_PAGE, reconfigure="w1")
    marker = marker_of(result, "schedule_workday_morning_time")
    assert suggested_value(marker) == "21:00:00"

    unchanged = day_inherit("workday", schedule_workday_morning_time="21:00:00")
    result = await configure_subentry_flow(hass, result, unchanged)
    assert result["step_id"] == WORKDAY_PAGE
    assert result["errors"]["schedule_workday_morning_time"] == "invalid_combination"

    result = await submit_steps(
        hass, result, [day_inherit("workday"), *_rest_after(WORKDAY_PAGE)]
    )
    assert result["reason"] == "reconfigure_successful"
    assert _own(entry, "w1") == {}


def test_reference_without_domains_offers_every_entity() -> None:
    """The entity domains are a convenience of the form; without them nothing is filtered."""
    context = LevelContext(level=Level.GLOBAL, own={}, house_title="House")
    catalog = Catalog(
        registry=features.CATALOG.registry,
        features=(
            FeatureForm(
                "daily_routine",
                (StepForm("general", (FieldForm("schedule_season_source"),)),),
            ),
        ),
        resolve=features.CATALOG.resolve,
    )
    page = catalog.features[0].steps[0]

    schema = inheritance.build_schema(
        catalog, page.fields, context, inheritance.inherited_settings(catalog, context)
    ).schema

    assert "domain" not in schema["schedule_season_source"].config
    filtered = schema_of(
        {
            "data_schema": inheritance.build_schema(
                features.CATALOG,
                DAILY_ROUTINE.steps[0].fields,
                context,
                inheritance.inherited_settings(features.CATALOG, context),
            )
        }
    )["schedule_season_source"]
    assert "binary_sensor" in filtered.config["domain"]


def test_value_without_a_form_value_is_refused_loudly() -> None:
    """A kind that no control can carry raises instead of showing something wrong."""
    definition = features.CATALOG.definitions["shading_temperature_tiers"]

    with pytest.raises(TypeError, match="has no form value"):
        inheritance.stored_form(
            definition, FieldForm("shading_temperature_tiers"), definition.default
        )
