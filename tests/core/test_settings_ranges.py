"""The range and the unit of a number or a duration live in its registry entry.

The forms give their number boxes these bounds, the reader refuses a stored
number outside them, and the documentation states them, so a range exists
once. The value rules of ``WindowConfig`` agree with every range: a bound is
accepted by the window configuration, and the next value outside it is refused
by the reader already.
"""

import dataclasses
from datetime import timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.model import (
    CapabilityProfile,
    FunctionId,
    MemberConfig,
    Position,
    WindowConfig,
)
from custom_components.roller_shutter_suite.core.model._data import as_int, as_str
from custom_components.roller_shutter_suite.core.settings import (
    POSITION_RANGE,
    WINDOW_SETTINGS,
    PartialSettings,
    SettingDefinition,
    SettingKind,
    SettingProblem,
    ValueRange,
    format_number,
    resolve_window,
    settings_from_stored,
)

_TEXT: Any = "0"
_MEMBER = MemberConfig(
    "cover.example_window",
    CapabilityProfile(
        supports_open_close=True,
        supports_set_position=True,
        supports_stop=True,
        reports_position=True,
        travel_time_up=timedelta(minutes=1),
        travel_time_down=timedelta(minutes=1),
    ),
)
_RANGED = [
    definition
    for definition in WINDOW_SETTINGS.definitions
    if definition.value_range is not None
]


def test_number_is_written_without_the_fraction_of_a_whole_number() -> None:
    """A whole number never appears as ``80.0``; a fraction stays."""
    assert format_number(80.0) == "80"
    assert format_number(-720) == "-720"
    assert format_number(-100.0) == "-100"
    assert format_number(22.5) == "22.5"
    assert format_number(0.1) == "0.1"


def test_range_contains_both_bounds_and_nothing_outside() -> None:
    """Both bounds are included; a missing bound does not limit."""
    closed = ValueRange(0, 100)
    assert closed.contains(0)
    assert closed.contains(100)
    assert not closed.contains(-0.5)
    assert not closed.contains(100.5)
    assert ValueRange(minimum=1).contains(10**9)
    assert ValueRange(maximum=5).contains(-(10**9))
    assert not ValueRange(maximum=5).contains(6)


def test_refusal_says_the_range_in_english_for_logs() -> None:
    """The text is for logs; a user sees a translated error instead."""
    assert ValueRange(-720, 720).refusal() == "expected a value from -720 to 720"
    assert ValueRange(minimum=0).refusal() == "expected a value of at least 0"
    assert ValueRange(maximum=10.0).refusal() == "expected a value of at most 10"


@pytest.mark.parametrize(
    ("build", "error", "message"),
    [
        (ValueRange, ValueError, "at least one bound"),
        (lambda: ValueRange(1, 0), ValueError, "above its maximum"),
        (lambda: ValueRange(minimum=float("nan")), ValueError, "finite"),
        (lambda: ValueRange(maximum=float("inf")), ValueError, "finite"),
        (lambda: ValueRange(minimum=True), TypeError, "number"),
        (lambda: ValueRange(minimum=_TEXT), TypeError, "number"),
    ],
    ids=["no bound", "reversed", "nan", "infinite", "boolean", "text"],
)
def test_range_refuses_what_makes_no_sense(
    build: Any, error: type[Exception], message: str
) -> None:
    """A range of the registry is checked when it is written."""
    with pytest.raises(error, match=message):
        build()


def _entry(**changes: Any) -> SettingDefinition[Any]:
    fields: dict[str, Any] = {
        "key": "example",
        "kind": SettingKind.NUMBER,
        "function": FunctionId.SCHEDULE,
        "default": 1,
        "parse": as_int,
    }
    return SettingDefinition(**(fields | changes))


def test_only_a_number_or_a_duration_has_a_range_and_only_a_number_a_unit() -> None:
    """A duration is stored in seconds; the form says in which unit it is entered."""
    assert _entry(value_range=ValueRange(0, 5), unit="%").unit == "%"
    duration = _entry(kind=SettingKind.DURATION, value_range=ValueRange(minimum=0))
    assert duration.value_range == ValueRange(minimum=0)
    with pytest.raises(ValueError, match="only a number or a duration has a range"):
        _entry(kind=SettingKind.TIME, parse=as_str, value_range=ValueRange(0, 5))
    with pytest.raises(ValueError, match="only a number states a unit"):
        _entry(kind=SettingKind.DURATION, unit="min")
    with pytest.raises(TypeError, match="the range of a setting"):
        _entry(value_range=(0, 5))
    with pytest.raises(ValueError, match="the unit of a setting"):
        _entry(unit="")


def test_out_of_range_judges_numbers_only() -> None:
    """Text, booleans and an entry without a range are left to the reader."""
    entry = _entry(value_range=ValueRange(0, 5))
    assert entry.out_of_range(6)
    assert entry.out_of_range(-0.5)
    assert not entry.out_of_range(5)
    assert not entry.out_of_range(True)
    assert not entry.out_of_range("9")
    assert not _entry().out_of_range(10**9)


def test_every_position_of_the_registry_has_the_range_of_a_position() -> None:
    """A position is a whole number from 0 to 100, in percent, wherever it is set."""
    defaults = {entry.name: entry.default for entry in dataclasses.fields(WindowConfig)}
    positions = [
        definition
        for definition in WINDOW_SETTINGS.definitions
        if isinstance(defaults.get(definition.key), Position)
    ]

    assert len(positions) >= 4  # noqa: PLR2004 - the positions of the schedule and more
    for definition in positions:
        assert definition.value_range == POSITION_RANGE, definition.key
        assert definition.unit == "%", definition.key


def _stored_bound(definition: SettingDefinition[Any], bound: float) -> Any:
    whole = float(bound).is_integer()
    if definition.kind is SettingKind.DURATION or whole:
        return int(bound)
    return bound


@pytest.mark.parametrize("definition", _RANGED, ids=lambda entry: entry.key)
def test_every_bound_is_taken_and_the_next_value_outside_is_refused(
    definition: SettingDefinition[Any],
) -> None:
    """The range of the entry and the value rules of the window agree.

    Each bound, stored as the own value of a window, passes the value rules
    of ``WindowConfig`` for single values. One step outside, the reader
    refuses it as ``invalid``.
    """
    value_range = definition.value_range
    assert value_range is not None
    for bound, outside in (
        (value_range.minimum, -1),
        (value_range.maximum, 1),
    ):
        if bound is None:
            continue
        stored = _stored_bound(definition, bound)
        resolution = resolve_window(
            window_id="w1",
            members=(_MEMBER,),
            global_settings=PartialSettings(),
            window_settings=settings_from_stored(
                {definition.key: stored}, WINDOW_SETTINGS
            ),
        )
        # A rule over several settings may still refuse a bound together with
        # the defaults of the others (a calibration); the value itself is taken.
        single = [
            fault
            for fault in resolution.settings.faults
            if fault.problem is not SettingProblem.COMBINATION
        ]
        assert not single, (definition.key, stored)
        partial = settings_from_stored(
            {definition.key: stored + outside}, WINDOW_SETTINGS
        )
        assert [(fault.key, fault.problem) for fault in partial.faults] == [
            (definition.key, SettingProblem.INVALID)
        ]
