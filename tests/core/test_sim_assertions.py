"""The assertions of the simulation, judged on records built by hand."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.roller_shutter_suite.core.model import (
    DayTriggers,
    Decision,
    Direction,
    GateOutcome,
    Layer,
    MemberTarget,
    MovementState,
    Observation,
    Position,
    Wish,
    WishClass,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.schedule_kit import config, fixed, sun_event
from tests.sim.assertions import (
    ScenarioAssertionError,
    assert_at_most_movements_per_day,
    assert_min_interval,
    assert_no_command_loop,
    assert_no_commands,
    assert_no_intermediate_position,
    assert_schedule_commands_inside_clamps,
    movements_per_day,
)
from tests.sim.record import Entry, EntryKind, Record, decision_summary

ZONE = ZoneInfo("Europe/Berlin")
WINDOW = "window_example"
MEMBER = "cover.example_window"
MONDAY = datetime(2026, 9, 21, tzinfo=ZONE)
CONFIG = config()  # workdays 06:30 and 20:00, fixed
TWICE = 2
FOUR_LINES = 4


def at(hour: int, minute: int = 0, second: int = 0, day: int = 21) -> datetime:
    """Return a local time of the Monday, or of another day of that week."""
    return MONDAY.replace(day=day, hour=hour, minute=minute, second=second)


def sent_decision(reason: ReasonCode, target: int) -> Decision:
    """Return a decision of the schedule that sends the target."""
    direction = (
        Direction.RAISE_ONLY
        if reason is ReasonCode.SCHEDULE_DAY
        else Direction.LOWER_ONLY
    )
    return Decision(
        winning_wish=Wish.target(
            Layer.SCHEDULE, reason, Position(target), direction=direction
        ),
        targets=(MemberTarget(MEMBER, Position(target)),),
        gate=GateOutcome.send(),
    )


def send(
    moment: datetime,
    target: int,
    reason: ReasonCode = ReasonCode.SCHEDULE_DAY,
    wish_class: WishClass = WishClass.COMFORT,
) -> list[Entry]:
    """Return the two entries of a send: the decision and the command."""
    return [
        Entry(
            moment,
            EntryKind.DECISION,
            "d",
            window_id=WINDOW,
            target=Position(target),
            wish_class=wish_class,
            decision=sent_decision(reason, target),
        ),
        Entry(
            moment,
            EntryKind.COMMAND,
            f"send {target}",
            window_id=WINDOW,
            member_id=MEMBER,
            target=Position(target),
            wish_class=wish_class,
        ),
    ]


def report(moment: datetime, position: int) -> Entry:
    """Return a report entry of the member at rest."""
    return Entry(
        moment,
        EntryKind.REPORT,
        f"open at {position}",
        window_id=WINDOW,
        member_id=MEMBER,
        observation=Observation(MovementState.RESTING, Position(position)),
    )


def record(*entries: Entry | list[Entry]) -> Record:
    """Return a record with the entries, flattened."""
    result = Record(ZONE)
    for entry in entries:
        if isinstance(entry, list):
            for one in entry:
                result.add(one)
        else:
            result.add(entry)
    return result


# --- Movements per day ------------------------------------------------------------------------


def test_movements_are_counted_per_window_and_local_date() -> None:
    """One send is one movement, however many members it has."""
    rec = record(
        send(at(6, 30), 100),
        send(at(20, 0), 0, ReasonCode.SCHEDULE_NIGHT),
        send(at(6, 30, day=22), 100),
    )

    counts = movements_per_day(rec, WINDOW)
    assert counts.counts == {MONDAY.date(): 2, MONDAY.date().replace(day=22): 1}
    assert counts.most == TWICE
    assert_at_most_movements_per_day(rec, 2)


def test_too_many_movements_on_a_day_point_at_the_third() -> None:
    """The message names the window, the day and the count, and shows the moment."""
    rec = record(send(at(6, 30), 100), send(at(9, 0), 50), send(at(12, 0), 100))

    with pytest.raises(ScenarioAssertionError) as caught:
        assert_at_most_movements_per_day(rec, 2)
    assert "moved 3 times" in str(caught.value)
    assert caught.value.moment == at(12, 0)
    assert "12:00:00" in str(caught.value)


def test_the_start_of_a_run_can_be_left_out() -> None:
    """A movement before ``since`` does not count."""
    rec = record(
        send(at(0, 0), 0, ReasonCode.SCHEDULE_NIGHT),
        send(at(6, 30), 100),
        send(at(20, 0), 0, ReasonCode.SCHEDULE_NIGHT),
    )

    with pytest.raises(ScenarioAssertionError):
        assert_at_most_movements_per_day(rec, 2)
    assert_at_most_movements_per_day(rec, 2, since=at(1, 0))


# --- Minimum interval -------------------------------------------------------------------------


def test_two_comfort_movements_inside_the_interval_are_found() -> None:
    """The default interval is ten minutes; protection movements do not count."""
    rec = record(send(at(6, 30), 100), send(at(6, 35), 50))
    with pytest.raises(ScenarioAssertionError, match="closer than"):
        assert_min_interval(rec, [CONFIG])

    calm = record(send(at(6, 30), 100), send(at(6, 41), 50))
    assert_min_interval(calm, [CONFIG])

    storm = record(
        send(at(6, 30), 100),
        send(at(6, 32), 0, ReasonCode.PROTECTION_EVENT, WishClass.PROTECTION),
    )
    assert_min_interval(storm, [CONFIG])


# --- Command loop -------------------------------------------------------------------------------


def test_a_repeated_command_without_a_report_in_between_is_a_loop() -> None:
    """The same member, the same target, nothing observed in between."""
    looping = record(send(at(6, 30), 100), send(at(6, 31), 100))
    with pytest.raises(ScenarioAssertionError, match="command loop"):
        assert_no_command_loop(looping)

    fine = record(
        send(at(6, 30), 100), report(at(6, 30, 20), 100), send(at(6, 31), 100)
    )
    assert_no_command_loop(fine)

    other_target = record(send(at(6, 30), 100), send(at(6, 31), 50))
    assert_no_command_loop(other_target)


# --- No intermediate position ------------------------------------------------------------------


def test_an_intermediate_position_during_the_storm_is_found() -> None:
    """Inside the span only 0 and 100 are allowed; outside it anything."""
    rec = record(
        send(at(13, 0), 50),
        send(at(14, 0), 0, ReasonCode.PROTECTION_EVENT, WishClass.PROTECTION),
        send(at(15, 0), 40),
    )

    with pytest.raises(ScenarioAssertionError, match="intermediate position 40"):
        assert_no_intermediate_position(rec, WINDOW, at(14, 0), at(16, 0))
    assert_no_intermediate_position(rec, WINDOW, at(14, 0), at(14, 30))


# --- Inside the clamps ---------------------------------------------------------------------------


def test_a_schedule_movement_at_its_fixed_time_is_inside() -> None:
    """At the fixed time, or a minute later, it is the trigger's movement."""
    rec = record(
        send(at(6, 30), 100), send(at(20, 0, 30), 0, ReasonCode.SCHEDULE_NIGHT)
    )
    assert_schedule_commands_inside_clamps(rec, CONFIG)


def test_a_schedule_movement_at_another_time_is_outside() -> None:
    """A morning opening at noon is not the morning trigger's."""
    rec = record(send(at(12, 0), 100))
    with pytest.raises(ScenarioAssertionError, match="outside 06:30 to 06:30"):
        assert_schedule_commands_inside_clamps(rec, CONFIG)
    assert_schedule_commands_inside_clamps(rec, CONFIG, since=at(13, 0))


def test_a_sun_trigger_is_judged_by_its_clamps() -> None:
    """With sunset as the evening, anything between the clamps is fine."""
    sunset = config(
        workday=DayTriggers(fixed(6, 30), sun_event((time(17, 0), time(22, 0))))
    )
    rec = record(send(at(19, 20, 18), 0, ReasonCode.SCHEDULE_NIGHT))
    assert_schedule_commands_inside_clamps(rec, sunset)
    late = record(send(at(22, 30), 0, ReasonCode.SCHEDULE_NIGHT))
    with pytest.raises(ScenarioAssertionError, match="outside 17:00 to 22:00"):
        assert_schedule_commands_inside_clamps(late, sunset)


def test_a_movement_of_another_layer_is_not_judged_by_the_clamps() -> None:
    """A protection movement at midnight is not the schedule's."""
    rec = record(send(at(0, 0), 0, ReasonCode.PROTECTION_EVENT, WishClass.PROTECTION))
    assert_schedule_commands_inside_clamps(rec, CONFIG)


# --- No commands ---------------------------------------------------------------------------------


def test_no_commands_finds_the_first_one() -> None:
    """A window that may not move was sent something."""
    rec = record(send(at(6, 30), 100))
    with pytest.raises(ScenarioAssertionError, match="although nothing may move"):
        assert_no_commands(rec, WINDOW)
    assert_no_commands(record(), WINDOW)


# --- The record and the timeline -------------------------------------------------------------------


def test_the_timeline_is_printed_in_the_local_zone_and_can_be_filtered() -> None:
    """Every entry is one line with the local time, the kind, the subject and the summary."""
    rec = record(
        send(at(6, 30), 100),
        report(at(6, 30, 20), 100),
        Entry(at(7, 0), EntryKind.RESTART, "restart"),
    )

    lines = rec.timeline().splitlines()
    assert len(lines) == FOUR_LINES
    assert lines[0].startswith(
        "2026-09-21 06:30:00.000 +0200  decision  window_example"
    )
    assert lines[1].endswith("send 100")
    assert "[cover.example_window]" in lines[2]
    assert rec.timeline(kinds=[EntryKind.COMMAND]).count("\n") == 0
    assert rec.timeline(window_id="another").strip() == lines[3].strip()
    assert rec.timeline(since=at(6, 45)) == lines[3]
    assert rec.around(at(6, 30), span=timedelta(seconds=30)).splitlines() == lines[:3]


def test_a_decision_summary_names_wish_constraints_and_gate() -> None:
    """The one readable line of a decision."""
    decision = sent_decision(ReasonCode.SCHEDULE_DAY, 100)
    assert (
        decision_summary(decision) == "schedule: schedule_day | wants 100 | send: sent"
    )
    assert decision_summary(Decision(winning_wish=None)) == "no layer has an opinion"
    held = Decision(
        winning_wish=Wish.leave_alone(Layer.FIRE, ReasonCode.FIRE_UNACKNOWLEDGED)
    )
    assert decision_summary(held) == "fire: fire_unacknowledged | (leave_alone)"


def test_an_entry_is_recorded_at_an_aware_instant() -> None:
    """A naive instant is refused; an aware one is kept in UTC."""
    with pytest.raises(ValueError, match="timezone-aware"):
        Entry(datetime(2026, 9, 21, 6, 30), EntryKind.EVENT, "x")  # noqa: DTZ001
    entry = Entry(at(6, 30), EntryKind.EVENT, "x")
    assert entry.at.tzinfo is UTC
    assert entry.at == at(6, 30)
