"""The form description fits the registry of the core, and is refused if it does not."""

from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.settings import (
    PartialSettings,
    SettingKind,
    schedule_trigger_keys,
)
from custom_components.roller_shutter_suite.features import CATALOG, FEATURES
from custom_components.roller_shutter_suite.features.daily_routine import (
    DAILY_ROUTINE,
)
from custom_components.roller_shutter_suite.flow.model import (
    PROBE_MEMBER,
    PROBE_WINDOW_ID,
    Catalog,
    FeatureForm,
    FieldForm,
    StepForm,
)
from tests.ha.helpers import EXAMPLE_REGISTRY, resolve_example

_EMPTY = PartialSettings()

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


def _stored(item: FieldForm, bound: float) -> Any:
    """Return a bound of a form field as the form would store it."""
    definition = CATALOG.definitions[item.key]
    if definition.kind is SettingKind.DURATION:
        return int(bound) * item.seconds_per_unit
    return int(bound) if float(bound).is_integer() else bound


@pytest.mark.parametrize(
    "item",
    [
        item
        for item in DAILY_ROUTINE.fields
        if (item.minimum, item.maximum) != (None,) * 2
    ],
    ids=lambda item: item.key,
)
def test_no_bound_of_a_form_is_wider_than_what_the_core_accepts(
    item: FieldForm,
) -> None:
    """A form never offers a value that the core refuses.

    The bounds of a number box are a convenience of the form. The rules are
    those of the window configuration: every bound is read by the reader of
    the setting and handed to the resolver of the core as the own value of a
    window, which reports a refusal as a fault.
    """
    definition = CATALOG.definitions[item.key]
    for bound in (item.minimum, item.maximum):
        if bound is None:
            continue
        value = definition.parse(_stored(item, bound))
        resolution = CATALOG.resolve(
            window_id=PROBE_WINDOW_ID,
            members=(PROBE_MEMBER,),
            global_settings=_EMPTY,
            window_settings=_EMPTY.with_value(item.key, value),
        )
        assert not resolution.settings.faults, (item.key, bound)


def test_bound_that_is_wider_than_the_core_is_noticed() -> None:
    """The counterpart: the check above sees a bound that the core refuses."""
    definition = CATALOG.definitions["schedule_random_offset"]
    value = definition.parse(31 * 60)

    resolution = CATALOG.resolve(
        window_id=PROBE_WINDOW_ID,
        members=(PROBE_MEMBER,),
        global_settings=_EMPTY,
        window_settings=_EMPTY.with_value("schedule_random_offset", value),
    )

    assert [fault.key for fault in resolution.settings.faults] == [
        "schedule_random_offset"
    ]


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


def test_duration_needs_a_unit_of_at_least_one_second() -> None:
    """A duration is stored in whole seconds."""
    with pytest.raises(ValueError, match="too small"):
        FieldForm("schedule_random_offset", seconds_per_unit=0)


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
