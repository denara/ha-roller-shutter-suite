"""The capability settings of a member in the settings registry of the core (section 8.1).

The position source cannot be detected, so the user states it per member,
and so is the tolerance, which a user widens for a cover that settles off
its target; block H10 builds the form from ``CAPABILITY_SETTINGS``. Neither
has a fault value: a faulty stored source is read as ``calculated``, a faulty
stored tolerance as none stated, so the default of the source applies. A
smaller tolerance never lets a movement by hand pass as the integration's own.
"""

import pytest

from custom_components.roller_shutter_suite.core.model import (
    DEFAULT_TOLERANCE_CALCULATED,
    DEFAULT_TOLERANCE_MEASURED,
    MAX_STATED_TOLERANCE,
    MIN_TOLERANCE,
    PositionOwner,
    PositionSource,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from custom_components.roller_shutter_suite.core.settings import (
    CAPABILITY_SETTINGS,
    PERCENT,
    SettingKind,
    ValueRange,
    position_source_from_stored,
    stated_tolerance_from_stored,
    tolerance_from_stored,
)
from tests.core.arbiter_kit import LEFT, profile
from tests.core.tracking_kit import codes, driver, moving_up, resting


def test_the_registry_holds_the_position_source_and_the_tolerance() -> None:
    """The two values of the capability profile a user states."""
    assert [d.key for d in CAPABILITY_SETTINGS.definitions] == [
        "position_source",
        "tolerance",
    ]


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
