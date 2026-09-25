"""The form description fits the registry of the core, and is refused if it does not."""

import dataclasses

import pytest

from custom_components.roller_shutter_suite.core.settings import (
    SettingKind,
    schedule_trigger_keys,
)
from custom_components.roller_shutter_suite.features import CATALOG, FEATURES
from custom_components.roller_shutter_suite.features.daily_routine import (
    DAILY_ROUTINE,
)
from custom_components.roller_shutter_suite.flow.model import (
    DURATION_UNITS,
    Catalog,
    FeatureForm,
    FieldForm,
    NumberBounds,
    StepForm,
)
from tests.ha.helpers import EXAMPLE_REGISTRY, resolve_example

NOT_OFFERED_YET = {
    # The conditional morning opening is not built; the core keeps its place.
    "morning_condition_source",
    # It has one value.
    "schedule_profile",
}


def _catalog(*features: FeatureForm) -> Catalog:
    return Catalog(
        registry=EXAMPLE_REGISTRY, features=features, resolve=resolve_example
    )


def _feature(*fields: FieldForm, switch: str | None = None) -> FeatureForm:
    return FeatureForm("a", (StepForm("page", fields),), switch)


def test_catalog_of_the_integration_is_built_from_the_registry_of_the_core() -> None:
    """Every form field of the shipped features is a setting the core knows."""
    assert CATALOG.features == FEATURES
    assert CATALOG.form_keys <= set(CATALOG.registry.keys)
    general = DAILY_ROUTINE.steps[0]
    assert CATALOG.step("feature_daily_routine_general") is general
    assert CATALOG.step("feature_example_absent") is None


def test_daily_routine_offers_every_schedule_setting_that_is_built() -> None:
    """The forms follow the registry: nothing of the schedule is forgotten."""
    schedule = {key for key in CATALOG.registry.keys if key.startswith("schedule_")}

    assert schedule - CATALOG.form_keys == {"schedule_profile"}
    assert not CATALOG.form_keys & NOT_OFFERED_YET
    assert DAILY_ROUTINE.switch == "schedule_enabled"


def test_trigger_fields_are_generated_from_the_list_of_the_core() -> None:
    """Day type, edge, field: the forms walk the same list as the registry."""
    pages = {step.name: step for step in DAILY_ROUTINE.steps}
    generated = [
        item.key
        for day_type in ("workday", "weekend", "holiday")
        for item in pages[day_type].fields
    ]

    assert generated == list(schedule_trigger_keys())
    # Kind and time are in sight; what only some kinds use is for experts.
    for day_type in ("workday", "weekend", "holiday"):
        in_sight = [item.key for item in pages[day_type].fields if not item.expert]
        assert in_sight == [
            f"schedule_{day_type}_{edge}_{field}"
            for edge in ("morning", "evening")
            for field in ("kind", "time")
        ]


def test_form_model_carries_no_bounds_and_no_unit_of_its_own() -> None:
    """One source: the range and the unit of a number live in the registry entry.

    A form describes where a field stands and how it is entered, never which
    values are valid. The bounds of every number box are read from the
    registry of the core, the same entry whose range the reader applies.
    """
    names = {entry.name for entry in dataclasses.fields(FieldForm)}

    assert not names & {"minimum", "maximum", "unit", "min", "max", "bounds"}
    assert names == {
        "key",
        "expert",
        "step",
        "seconds_per_unit",
        "entity_domains",
        "options_key",
        "form_name",
    }


def _number_fields() -> list[FieldForm]:
    return [
        item
        for feature in FEATURES
        for item in feature.fields
        if CATALOG.definitions[item.key].kind
        in (SettingKind.NUMBER, SettingKind.DURATION)
    ]


@pytest.mark.parametrize("item", _number_fields(), ids=lambda item: item.key)
def test_every_number_box_has_the_range_and_unit_of_its_registry_entry(
    item: FieldForm,
) -> None:
    """A number keeps its range; a duration shows the whole units within it."""
    definition = CATALOG.definitions[item.key]
    value_range = definition.value_range
    bounds = CATALOG.number_bounds(item)

    assert value_range is not None, f"{item.key} is a number without a range"
    if definition.kind is SettingKind.NUMBER:
        assert (bounds.minimum, bounds.maximum) == (
            value_range.minimum,
            value_range.maximum,
        )
        assert bounds.unit == definition.unit
        assert bounds.unit is not None
    else:
        size = item.seconds_per_unit
        for bound, limit in (
            (bounds.minimum, value_range.minimum),
            (bounds.maximum, value_range.maximum),
        ):
            assert (bound is None) is (limit is None)
            if bound is not None and limit is not None:
                assert value_range.contains(bound * size)
                assert isinstance(bound, int)
        assert bounds.unit == DURATION_UNITS[size]
    assert bounds.step == item.step


def test_bounds_of_a_duration_are_the_whole_units_inside_its_range() -> None:
    """Re-evaluation: longer than zero seconds, so at least one whole minute."""
    reevaluate = next(
        item for item in _number_fields() if item.key == "reevaluate_after"
    )
    offset = next(
        item for item in _number_fields() if item.key == "schedule_random_offset"
    )

    assert CATALOG.number_bounds(reevaluate) == NumberBounds(1, None, "min", 1)
    assert CATALOG.number_bounds(offset) == NumberBounds(0, 30, "min", 1)


def test_whole_bounds_are_whole_numbers_and_texts_have_no_fraction() -> None:
    """The elevation of a trigger is a float in the core, and still no "90.0"."""
    elevation = next(
        item
        for item in _number_fields()
        if item.key == "schedule_workday_morning_elevation"
    )
    bounds = CATALOG.number_bounds(elevation)

    assert bounds == NumberBounds(-90, 90, "°", 0.1)
    assert str(bounds.minimum) == "-90"
    assert bounds.text(-90.0) == "-90 °"
    assert bounds.text(22.5, with_unit=False) == "22.5"
    assert NumberBounds(None, None, None, 1).text(5.0) == "5"


@pytest.mark.parametrize(
    ("feature", "message"),
    [
        (_feature(FieldForm("example_absent")), "does not know"),
        (_feature(switch="example_absent"), "does not know"),
        (_feature(switch="schedule_morning_position"), "inheritable boolean"),
        (_feature(FieldForm("shading_temperature_tiers")), "step of its own"),
        (_feature(FieldForm("schedule_summer_first_day", expert=True)), "stay out"),
        (
            _feature(FieldForm("schedule_enabled"), switch="schedule_enabled"),
            "two forms",
        ),
        (
            FeatureForm("a", (StepForm("page", ()), StepForm("page", ()))),
            "same step ID",
        ),
    ],
    ids=[
        "unknown field",
        "unknown switch",
        "switch kind",
        "list",
        "section",
        "twice",
        "page twice",
    ],
)
def test_form_that_does_not_fit_the_registry_is_refused(
    feature: FeatureForm, message: str
) -> None:
    """The registry is the one description of the settings; a form cannot contradict it."""
    with pytest.raises(ValueError, match=message):
        _catalog(feature)


def test_duration_is_entered_in_a_known_unit() -> None:
    """A duration is stored in whole seconds and entered in seconds, minutes or hours."""
    for size in (0, 90):
        with pytest.raises(ValueError, match="is not one of"):
            FieldForm("schedule_random_offset", seconds_per_unit=size)


def test_switches_count_as_form_keys() -> None:
    """The switch of a feature is a form field like any other."""
    catalog = _catalog(
        _feature(FieldForm("schedule_summer_by_date"), switch="schedule_enabled")
    )

    assert catalog.form_keys == {"schedule_summer_by_date", "schedule_enabled"}


def test_field_is_named_by_its_key_unless_the_form_says_otherwise() -> None:
    """The form name carries what the key leaves to its documentation: the unit."""
    names = {item.key: item.name for item in DAILY_ROUTINE.fields}

    assert names["schedule_brightness_threshold"] == "schedule_brightness_threshold_lux"
    assert names["schedule_brightness_delay"] == "schedule_brightness_delay"
