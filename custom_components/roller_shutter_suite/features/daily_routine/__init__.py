"""The daily routine: what opens and closes the shutters over the day.

The settings are entries of the registry of the core (``schedule_*``). This
package only says how they appear in the forms: on which page, in the section
of expert values or not, and how their input controls look. The bounds given
here are a convenience of the controls; the core decides what is valid, and a
test fails if a bound is wider than what the core accepts.

The 36 settings of the triggers (day type, edge, field) are generated in the
core in one place. Their form descriptions are generated here in the same way
and from the same lists, and a test compares the result with
``schedule_trigger_keys()``.

**Not offered yet:** ``morning_condition_source`` (the conditional morning
opening is not built; the core only keeps its place) and ``schedule_profile``
(it has one value). Both stay in the registry and keep their stored values; no
form shows them.

**All fields of a trigger are shown**, whatever its kind: a form is static, so
a field cannot appear or disappear with the choice of another field of the
same page.
"""

from typing import Final

from custom_components.roller_shutter_suite.core.model import (
    SCHEDULE_DAY_TYPES,
    SCHEDULE_EDGES,
)
from custom_components.roller_shutter_suite.flow.model import (
    FeatureForm,
    FieldForm,
    StepForm,
)

_SWITCH_DOMAINS: Final = ("binary_sensor", "input_boolean", "switch", "schedule")
_DAY_DOMAINS: Final = (*_SWITCH_DOMAINS, "calendar")
_BRIGHTNESS_DOMAINS: Final = ("sensor", "number", "input_number")
_MINUTE: Final = 60

TRIGGER_KIND_OPTIONS: Final = "schedule_trigger_kind"
"""The six trigger kinds offer the same choice and share its translation."""

_GENERAL: Final = StepForm(
    name="general",
    fields=(
        FieldForm("schedule_morning_position", minimum=0, maximum=100, unit="%"),
        FieldForm("schedule_evening_position", minimum=0, maximum=100, unit="%"),
        FieldForm("schedule_workday_source", entity_domains=_SWITCH_DOMAINS),
        FieldForm("schedule_holiday_source", entity_domains=_DAY_DOMAINS),
        FieldForm("schedule_season_source", entity_domains=_SWITCH_DOMAINS),
        FieldForm("schedule_summer_by_date"),
        FieldForm("schedule_summer_first_day"),
        FieldForm("schedule_summer_last_day"),
        FieldForm("schedule_evening_position_summer", minimum=0, maximum=100, unit="%"),
        FieldForm("schedule_brightness_source", entity_domains=_BRIGHTNESS_DOMAINS),
        FieldForm(
            "schedule_brightness_threshold",
            minimum=0,
            step=0.1,
            unit="lx",
            # The key leaves the unit to its documentation; the form names it.
            form_name="schedule_brightness_threshold_lux",
        ),
        FieldForm(
            "schedule_brightness_delay",
            expert=True,
            minimum=0,
            unit="min",
            seconds_per_unit=_MINUTE,
        ),
        FieldForm(
            "schedule_random_offset",
            expert=True,
            minimum=0,
            maximum=30,
            unit="min",
            seconds_per_unit=_MINUTE,
        ),
    ),
)


def _trigger_fields(day_type: str, edge: str) -> tuple[FieldForm, ...]:
    """Return the fields of one trigger: kind and time in sight, the rest for experts."""
    prefix = f"schedule_{day_type}_{edge}"
    return (
        FieldForm(f"{prefix}_kind", options_key=TRIGGER_KIND_OPTIONS),
        FieldForm(f"{prefix}_time"),
        FieldForm(
            f"{prefix}_offset_minutes",
            expert=True,
            minimum=-720,
            maximum=720,
            unit="min",
        ),
        FieldForm(
            f"{prefix}_elevation",
            expert=True,
            minimum=-90,
            maximum=90,
            step=0.1,
            unit="°",
        ),
        FieldForm(f"{prefix}_not_before", expert=True),
        FieldForm(f"{prefix}_not_after", expert=True),
    )


def _day_type_step(day_type: str) -> StepForm:
    return StepForm(
        name=day_type,
        fields=tuple(
            item for edge in SCHEDULE_EDGES for item in _trigger_fields(day_type, edge)
        ),
    )


DAILY_ROUTINE: Final = FeatureForm(
    feature_id="daily_routine",
    switch="schedule_enabled",
    steps=(_GENERAL, *(_day_type_step(day_type) for day_type in SCHEDULE_DAY_TYPES)),
)
