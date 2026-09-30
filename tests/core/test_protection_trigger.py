"""The trigger state machine per kind of source, and the clock of a blind source.

Section 10.1: active and inactive come from a value; unknown (unavailable,
unknown, missing, a value of the wrong kind, a faulty trigger) changes
nothing. A number inside the hysteresis band changes nothing either, but it
is a value.
"""

from datetime import timedelta

import pytest

from custom_components.roller_shutter_suite.core.model import (
    AnySourceValue,
    BlindClock,
    ProtectionTrigger,
    SourceValue,
    TriggerType,
)
from custom_components.roller_shutter_suite.core.protection import (
    Reading,
    advance_blind_clock,
    blind_wake_up,
    is_blind,
    read_trigger,
)
from custom_components.roller_shutter_suite.core.protection.trigger import (
    missing_reason,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import NOW

SOURCE = "sensor.example_source"
BINARY = ProtectionTrigger(SOURCE)
CALM = ProtectionTrigger(SOURCE, invert=True)
STATES = ProtectionTrigger(SOURCE, TriggerType.STATES, states=("red", "on", "3"))
WIND = ProtectionTrigger(SOURCE, TriggerType.THRESHOLD, threshold=50, hysteresis=10)
PRESSURE = ProtectionTrigger(
    SOURCE, TriggerType.THRESHOLD, threshold=980, hysteresis=5, invert=True
)

UNKNOWN: AnySourceValue = SourceValue.unknown()
UNAVAILABLE: AnySourceValue = SourceValue.unavailable()


@pytest.mark.parametrize(
    ("trigger", "value", "reading"),
    [
        (BINARY, SourceValue.of(True), Reading.ACTIVE),
        (BINARY, SourceValue.of(False), Reading.INACTIVE),
        (BINARY, SourceValue.of("on"), Reading.UNKNOWN),
        (BINARY, SourceValue.of(1), Reading.UNKNOWN),
        (CALM, SourceValue.of(False), Reading.ACTIVE),
        (CALM, SourceValue.of(True), Reading.INACTIVE),
        (STATES, SourceValue.of("red"), Reading.ACTIVE),
        (STATES, SourceValue.of("green"), Reading.INACTIVE),
        (STATES, SourceValue.of(True), Reading.ACTIVE),
        (STATES, SourceValue.of(False), Reading.INACTIVE),
        (STATES, SourceValue.of(3.0), Reading.ACTIVE),
        (STATES, SourceValue.of(3.5), Reading.INACTIVE),
        (WIND, SourceValue.of(50), Reading.ACTIVE),
        (WIND, SourceValue.of(72.5), Reading.ACTIVE),
        (WIND, SourceValue.of(45), Reading.HOLD),
        (WIND, SourceValue.of(40), Reading.HOLD),
        (WIND, SourceValue.of(39.9), Reading.INACTIVE),
        (WIND, SourceValue.of(True), Reading.UNKNOWN),
        (WIND, SourceValue.of("strong"), Reading.UNKNOWN),
        (PRESSURE, SourceValue.of(975), Reading.ACTIVE),
        (PRESSURE, SourceValue.of(980), Reading.ACTIVE),
        (PRESSURE, SourceValue.of(985), Reading.HOLD),
        (PRESSURE, SourceValue.of(985.1), Reading.INACTIVE),
    ],
)
def test_a_value_of_the_source_reads_active_inactive_or_inside_the_band(
    trigger: ProtectionTrigger, value: AnySourceValue, reading: Reading
) -> None:
    """Binary with invert, states by their text, a threshold with hysteresis."""
    assert read_trigger(trigger, value) is reading


@pytest.mark.parametrize("trigger", [BINARY, STATES, WIND, None])
@pytest.mark.parametrize("value", [UNKNOWN, UNAVAILABLE, None])
def test_no_value_is_unknown_for_every_kind(
    trigger: ProtectionTrigger | None, value: AnySourceValue | None
) -> None:
    """Missing data is neither a warning nor an all-clear (D6)."""
    assert read_trigger(trigger, value) is Reading.UNKNOWN
    assert not Reading.UNKNOWN.has_value
    assert Reading.HOLD.has_value


def test_a_faulty_trigger_is_unknown_whatever_the_source_says() -> None:
    """``None``: the stored trigger could not be read."""
    assert read_trigger(None, SourceValue.of(True)) is Reading.UNKNOWN


def test_why_a_source_has_no_value() -> None:
    """Unknown, a value of the wrong kind, and unavailable or missing."""
    assert missing_reason(UNKNOWN) is ReasonCode.INPUT_UNKNOWN
    assert missing_reason(SourceValue.of("on")) is ReasonCode.INPUT_UNKNOWN
    assert missing_reason(UNAVAILABLE) is ReasonCode.INPUT_UNAVAILABLE
    assert missing_reason(None) is ReasonCode.INPUT_UNAVAILABLE


# --- The clock of a blind source ------------------------------------------------------

HOUR = timedelta(hours=1)


def test_the_clock_starts_runs_and_reports_once_per_blind_phase() -> None:
    """Default one hour; the event is due exactly once."""
    started, due = advance_blind_clock(None, has_value=False, now=NOW, blind_after=HOUR)
    assert started == BlindClock(NOW)
    assert not due
    assert blind_wake_up(started, HOUR) == NOW + HOUR
    assert not is_blind(started, now=NOW + timedelta(minutes=59), blind_after=HOUR)

    running, due = advance_blind_clock(
        started, has_value=False, now=NOW + timedelta(minutes=59), blind_after=HOUR
    )
    assert running == started
    assert not due

    reported, due = advance_blind_clock(
        running, has_value=False, now=NOW + HOUR, blind_after=HOUR
    )
    assert reported == BlindClock(NOW, reported=True)
    assert due
    assert is_blind(reported, now=NOW + HOUR, blind_after=HOUR)
    assert blind_wake_up(reported, HOUR) is None

    again, due = advance_blind_clock(
        reported, has_value=False, now=NOW + 5 * HOUR, blind_after=HOUR
    )
    assert again == reported
    assert not due


def test_a_value_ends_the_blind_phase_and_a_new_one_reports_again() -> None:
    """The repair issue disappears by itself when the source has a value again."""
    reported = BlindClock(NOW, reported=True)

    cleared, due = advance_blind_clock(
        reported, has_value=True, now=NOW + HOUR, blind_after=HOUR
    )
    assert cleared is None
    assert not due
    assert blind_wake_up(None, HOUR) is None
    assert not is_blind(None, now=NOW, blind_after=HOUR)

    restarted, _ = advance_blind_clock(
        cleared, has_value=False, now=NOW + 2 * HOUR, blind_after=HOUR
    )
    assert restarted == BlindClock(NOW + 2 * HOUR)


def test_a_changed_blind_time_applies_to_a_running_clock() -> None:
    """The time is a setting and is applied when the clock is judged."""
    clock = BlindClock(NOW)

    _, due = advance_blind_clock(
        clock,
        has_value=False,
        now=NOW + timedelta(minutes=20),
        blind_after=timedelta(minutes=15),
    )

    assert due
