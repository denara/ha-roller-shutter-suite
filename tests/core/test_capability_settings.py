"""The capability settings of a member in the settings registry of the core (section 8.1).

The position source cannot be detected, so the user states it per member,
and so is the tolerance, which a user widens for a cover that settles off
its target; block H10 builds the form from ``CAPABILITY_SETTINGS``. Neither
has a fault value: a faulty stored source is read as ``calculated``, a faulty
stored tolerance as none stated, so the default of the source applies. A
smaller tolerance never lets a movement by hand pass as the integration's own.
"""

from dataclasses import replace
from datetime import timedelta

import pytest

from custom_components.roller_shutter_suite.core.model import (
    DEFAULT_TOLERANCE_CALCULATED,
    DEFAULT_TOLERANCE_MEASURED,
    DEFAULT_TRAVEL_TIME,
    MAX_STATED_TOLERANCE,
    MIN_TOLERANCE,
    PositionOwner,
    PositionSource,
    ReportingKind,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from custom_components.roller_shutter_suite.core.settings import (
    CAPABILITY_SETTINGS,
    PERCENT,
    SettingKind,
    ValueRange,
    position_source_from_stored,
    reporting_kind_from_stored,
    reporting_time_from_stored,
    stated_capabilities,
    stated_tolerance_from_stored,
    tolerance_from_stored,
    travel_time_from_stored,
)
from tests.core.arbiter_kit import LEFT, profile
from tests.core.tracking_kit import codes, driver, moving_up, resting


def test_the_registry_holds_what_a_user_states_about_a_member() -> None:
    """The values of the capability profile a user states (section 8.1)."""
    assert [d.key for d in CAPABILITY_SETTINGS.definitions] == [
        "position_source",
        "tolerance",
        "reporting_kind",
        "reporting_time",
        "travel_time_up",
        "travel_time_down",
    ]
    for definition in CAPABILITY_SETTINGS.definitions:
        assert definition.function is None
        assert definition.inheritable is False
        assert not definition.has_fault_value


def test_the_reporting_kind_and_time_have_no_default() -> None:
    """Ruling of the project owner, 2026-10-01: a value that is not set is unknown."""
    kind, time = CAPABILITY_SETTINGS.definitions[2:4]

    assert (kind.key, kind.kind, kind.default) == (
        "reporting_kind",
        SettingKind.ENUMERATION,
        None,
    )
    assert (time.key, time.kind, time.default) == (
        "reporting_time",
        SettingKind.DURATION,
        None,
    )
    assert time.value_range == ValueRange(0, 600)


def test_the_travel_times_default_to_sixty_seconds() -> None:
    """Ruling 1 of the project owner for block H10: 60 s in each direction."""
    for definition in CAPABILITY_SETTINGS.definitions[4:]:
        assert definition.kind is SettingKind.DURATION
        assert definition.default == DEFAULT_TRAVEL_TIME == timedelta(seconds=60)
        assert definition.value_range == ValueRange(1, 600)


@pytest.mark.parametrize(
    ("stored", "kind", "time"),
    [
        ({"reporting_kind": "event_driven", "reporting_time": 30}, "event_driven", 30),
        ({"reporting_kind": "polled", "reporting_time": 60}, "polled", 60),
        ({"reporting_kind": "event_driven", "reporting_time": 0}, "event_driven", 0),
        ({}, None, None),
        ({"reporting_kind": "pushed", "reporting_time": -1}, None, None),
        ({"reporting_kind": None, "reporting_time": 601}, None, None),
        ({"reporting_kind": True, "reporting_time": "soon"}, None, None),
        ("not a mapping", None, None),
        # Today a decimal number is unknown, even a whole one such as 300.0.
        # This changes with maintenance item X07 of TASKS.md: a decimal number
        # with a whole value will be read as that whole number; a fraction
        # such as 30.5 stays unknown. A boolean is no number of seconds.
        (
            {"reporting_kind": "event_driven", "reporting_time": 300.0},
            "event_driven",
            None,
        ),
        (
            {"reporting_kind": "event_driven", "reporting_time": 0.0},
            "event_driven",
            None,
        ),
        (
            {"reporting_kind": "event_driven", "reporting_time": 30.5},
            "event_driven",
            None,
        ),
        (
            {"reporting_kind": "event_driven", "reporting_time": True},
            "event_driven",
            None,
        ),
    ],
    ids=[
        "event-driven",
        "polled",
        "at-once",
        "absent",
        "faulty",
        "null",
        "text",
        "x",
        "time-a-decimal-number",
        "time-zero-as-a-decimal-number",
        "time-a-fraction",
        "time-a-boolean",
    ],
)
def test_a_faulty_stored_reporting_kind_or_time_is_unknown(
    stored: object, kind: str | None, time: int | None
) -> None:
    """Never a value nobody entered: absent or faulty is unknown, never zero.

    The time is a whole number of seconds. The form never stores a decimal
    number or a boolean, so only data stored from elsewhere can carry one;
    today both are unknown (the comment at the cases names what X07 changes).
    """
    assert reporting_kind_from_stored(stored) == (
        None if kind is None else ReportingKind(kind)
    )
    assert reporting_time_from_stored(stored) == (
        None if time is None else timedelta(seconds=time)
    )


@pytest.mark.parametrize(
    ("stored", "up", "down"),
    [
        ({"travel_time_up": 25, "travel_time_down": 22}, 25, 22),
        ({}, 60, 60),
        ({"travel_time_up": 0, "travel_time_down": 601}, 60, 60),
        ({"travel_time_up": "long"}, 60, 60),
    ],
    ids=["stated", "absent", "out-of-range", "text"],
)
def test_a_travel_time_is_the_stated_one_or_the_default(
    stored: object, up: int, down: int
) -> None:
    """A faulty travel time is the default of 60 seconds."""
    assert travel_time_from_stored(stored, "travel_time_up") == timedelta(seconds=up)
    assert travel_time_from_stored(stored, "travel_time_down") == timedelta(
        seconds=down
    )


def test_the_profile_takes_what_the_user_stated() -> None:
    """``stated_capabilities`` hands every value into the capability profile."""
    base = profile(reporting_kind=None, reporting_time=None)
    stated = stated_capabilities(
        base,
        {
            "position_source": "measured",
            "tolerance": 4,
            "reporting_kind": "event_driven",
            "reporting_time": 45,
            "travel_time_up": 30,
            "travel_time_down": 28,
        },
    )

    assert stated.position_source is PositionSource.MEASURED
    assert stated.stated_tolerance == 4  # noqa: PLR2004
    assert stated.reporting_kind is ReportingKind.EVENT_DRIVEN
    assert stated.reporting_time == timedelta(seconds=45)
    assert (stated.travel_time_up, stated.travel_time_down) == (
        timedelta(seconds=30),
        timedelta(seconds=28),
    )
    assert stated_capabilities(base, None) == replace(
        base, travel_time_up=DEFAULT_TRAVEL_TIME, travel_time_down=DEFAULT_TRAVEL_TIME
    )


def test_the_position_source_is_a_setting_of_one_member_without_a_fault_value() -> None:
    """A value of the capability profile: no function, not inherited, no fault value."""
    definition = CAPABILITY_SETTINGS.definitions[0]

    assert definition.key == "position_source"
    assert definition.kind is SettingKind.ENUMERATION
    assert definition.function is None
    assert definition.inheritable is False
    assert not definition.has_fault_value
    assert definition.default is PositionSource.CALCULATED


@pytest.mark.parametrize(
    ("stored", "source"),
    [
        ({"position_source": "measured"}, PositionSource.MEASURED),
        ({"position_source": "calculated"}, PositionSource.CALCULATED),
        ({}, PositionSource.CALCULATED),
        ({"position_source": "laser"}, PositionSource.CALCULATED),
        ({"position_source": None}, PositionSource.CALCULATED),
        ({"position_source": "__none__"}, PositionSource.CALCULATED),
        ("not a mapping", PositionSource.CALCULATED),
    ],
    ids=["measured", "calculated", "absent", "unknown", "null", "none", "unreadable"],
)
def test_a_faulty_stored_position_source_is_read_as_calculated(
    stored: object, source: PositionSource
) -> None:
    """Absent, unknown, null, "none" or unreadable: the cautious default."""
    assert position_source_from_stored(stored) is source


def test_the_position_source_decides_the_default_tolerance() -> None:
    """2 for a calculated position, 3 for a measured one (section 8.3)."""
    calculated = profile(position_source=PositionSource.CALCULATED)
    measured = profile(position_source=PositionSource.MEASURED)

    assert calculated.tolerance == DEFAULT_TOLERANCE_CALCULATED
    assert measured.tolerance == DEFAULT_TOLERANCE_MEASURED


def test_the_tolerance_is_a_setting_of_one_member_without_a_fault_value() -> None:
    """Unset by default, a whole percent from 1 to 20, never inherited."""
    definition = CAPABILITY_SETTINGS.definitions[1]

    assert definition.key == "tolerance"
    assert definition.kind is SettingKind.NUMBER
    assert definition.function is None
    assert definition.inheritable is False
    assert not definition.has_fault_value
    assert definition.default is None
    assert definition.value_range == ValueRange(MIN_TOLERANCE, MAX_STATED_TOLERANCE)
    assert definition.unit == PERCENT
    assert (MIN_TOLERANCE, MAX_STATED_TOLERANCE) == (1, 20)


@pytest.mark.parametrize(
    ("stored", "stated", "tolerance"),
    [
        ({"tolerance": 5}, 5, 5),
        ({"tolerance": 1, "position_source": "measured"}, 1, 1),
        ({"tolerance": 20}, 20, 20),
        ({}, None, DEFAULT_TOLERANCE_CALCULATED),
        ({"position_source": "measured"}, None, DEFAULT_TOLERANCE_MEASURED),
        ({"tolerance": 0}, None, DEFAULT_TOLERANCE_CALCULATED),
        ({"tolerance": 21, "position_source": "measured"}, None, 3),
        ({"tolerance": 2.5}, None, DEFAULT_TOLERANCE_CALCULATED),
        ({"tolerance": "wide"}, None, DEFAULT_TOLERANCE_CALCULATED),
        ({"tolerance": True}, None, DEFAULT_TOLERANCE_CALCULATED),
        ({"tolerance": None}, None, DEFAULT_TOLERANCE_CALCULATED),
        ({"tolerance": 6, "position_source": "laser"}, 6, 6),
        ({"tolerance": 30, "position_source": "laser"}, None, 2),
        ("not a mapping", None, DEFAULT_TOLERANCE_CALCULATED),
    ],
    ids=[
        "stated",
        "stated-minimum",
        "stated-maximum",
        "unset-calculated",
        "unset-measured",
        "below-the-range",
        "above-the-range-measured",
        "not-whole",
        "text",
        "boolean",
        "null",
        "stated-with-a-faulty-source",
        "both-faulty",
        "unreadable",
    ],
)
def test_the_tolerance_resolves_to_the_stated_one_or_the_default_of_the_source(
    stored: object, stated: int | None, tolerance: int
) -> None:
    """A faulty stored tolerance is none stated: the position source decides."""
    assert stated_tolerance_from_stored(stored) == stated
    assert tolerance_from_stored(stored) == tolerance
    source = position_source_from_stored(stored)
    built = profile(position_source=source, stated_tolerance=stated)
    assert built.tolerance == tolerance


@pytest.mark.parametrize(
    ("stored", "detected"),
    [({}, True), ({"position_source": "measured"}, True), ({"tolerance": 5}, False)],
    ids=["default-calculated", "default-measured", "widened"],
)
def test_the_tracker_reads_the_stated_tolerance(
    stored: object, *, detected: bool
) -> None:
    """A cover that settles four percent short of its target (section 8.3).

    Within the default tolerance it looks like a person who stopped it; a
    user who widens the tolerance to five takes it for what it is.
    """
    member_profile = profile(
        position_source=position_source_from_stored(stored),
        stated_tolerance=stated_tolerance_from_stored(stored),
    )
    subject = driver(profiles={LEFT: member_profile})
    subject.report(resting(0))
    subject.recompute()
    subject.at(0.7).report(moving_up(4))
    subject.at(20).report(resting(96))
    subject.at(23).recompute()

    assert (ReasonCode.MANUAL_DETECTED in codes(subject.events)) is detected
    assert (subject.state.owner is PositionOwner.USER) is detected
