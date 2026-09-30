"""The scenarios of block C07 in the time-lapse simulation: fire and protection.

Situations 1 to 10 and 14 of section 4 of the specification, run with the real
fire and protection layers and the tracker: each test names the reason codes
the table names (winner / constraint / gate). Situations 4 and 5 use the
stand-in for lockout protection of block C08, situation 6 the stand-in for
sleep mode of block C11. Beyond the table: a storm source that drops out and
returns, the watchdog, two events at once, a fire during a storm, and
restarts during an active event, its waiting time and a release.
"""

from datetime import datetime, time, timedelta
from typing import Final

import pytest

from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    Decision,
    WishKind,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.sim.assertions import (
    assert_dams_follow_foreign_movements,
    assert_no_command_loop,
    assert_no_intermediate_position,
)
from tests.sim.record import EntryKind, Record
from tests.sim.scenarios import (
    MONDAY,
    PERSON_LOWERS,
    PERSON_OPENS,
    PROTECTION_RESTARTS,
    local,
    run_named,
    storm_return_with_restart,
    storm_stuck_with_restart,
)

WINDOW: Final = "window_example"


def at(hour: int, minute: int = 0, second: float = 0) -> datetime:
    """Return a local time of the Monday of the scenarios."""
    whole = int(second)
    micro = round((second - whole) * 1_000_000)
    return local(MONDAY, time(hour, minute, whole, micro))


def decisions(record: Record, since: datetime, until: datetime) -> list[Decision]:
    """Return the decisions of the window in a span, both ends included."""
    return [
        entry.decision
        for entry in record.decisions(WINDOW)
        if entry.decision is not None and since <= entry.at <= until
    ]


def first_decision(record: Record, moment: datetime) -> Decision:
    """Return the first decision of the window at or after a moment."""
    return next(
        entry.decision
        for entry in record.decisions(WINDOW)
        if entry.decision is not None and entry.at >= moment
    )


def reasons(decision: Decision) -> tuple[ReasonCode | None, ...]:
    """Return winner / constraints / gate, as the table of section 4 names them."""
    winner = None if decision.winning_wish is None else decision.winning_wish.reason
    gate = None if decision.gate is None else decision.gate.reason
    return (winner, *(result.reason for result in decision.constraints), gate)


def sends(record: Record) -> list[tuple[str, int, str]]:
    """Return (local time, target, reason) of every command of the window.

    Until 18:00: the evening closing of the schedule is not the subject.
    """
    return [
        (
            entry.at.astimezone(record.zone).strftime("%H:%M:%S"),
            entry.target.value,
            entry.summary.rsplit(", ", 1)[1].rstrip(")"),
        )
        for entry in record.commands(WINDOW)
        if entry.target is not None and entry.at < at(18)
    ]


def event_codes(record: Record, *codes: ReasonCode) -> list[ReasonCode]:
    """Return the codes of the events of the window, of the given codes only."""
    return [
        entry.event.code
        for entry in record.events(WINDOW, *codes)
        if entry.event is not None
    ]


# --- Situations 1 to 3a: the fire alarm -----------------------------------------------


def test_situations_1_to_3_fire_under_the_lock_in_dry_run_and_in_mode_off() -> None:
    """Locked and dry-run: nothing moves, fire names itself; off: opens at once."""
    locked = run_named("fire-locked").record
    dry = run_named("fire-dry-run").record
    off = run_named("fire-off").record

    assert reasons(first_decision(locked, at(10))) == (
        ReasonCode.FIRE_ALARM,
        ReasonCode.MAINTENANCE_LOCK,
    )
    assert not locked.commands(WINDOW)
    dry_run = first_decision(dry, at(10))
    assert reasons(dry_run) == (ReasonCode.FIRE_ALARM, ReasonCode.DRY_RUN)
    assert dry_run.gate is not None
    assert dry_run.gate.would_send[0].position == FULLY_OPEN
    assert not dry.commands(WINDOW)
    assert reasons(first_decision(off, at(10))) == (
        ReasonCode.FIRE_ALARM,
        ReasonCode.SENT,
    )
    assert ("10:00:00", 100, "fire_alarm") in sends(off)


def test_situation_3a_a_hand_movement_after_a_false_alarm_is_never_undone() -> None:
    """``fire_unacknowledged`` / — / — plus ``manual_detected``; the override protects."""
    simulation = run_named("fire-unacknowledged")
    record = simulation.record

    assert reasons(first_decision(record, at(13, 5))) == (
        ReasonCode.FIRE_UNACKNOWLEDGED,
        None,
    )
    assert event_codes(record, ReasonCode.MANUAL_DETECTED) == [
        ReasonCode.MANUAL_DETECTED
    ]
    after = first_decision(record, at(14))
    assert reasons(after) == (ReasonCode.SCHEDULE_DAY, ReasonCode.MANUAL_OVERRIDE)
    assert sends(record) == [("13:00:00", 100, "fire_alarm")]
    assert simulation.world.cover("cover.example_window").real_position(
        simulation.now
    ) == (FULLY_CLOSED.value)
    assert_dams_follow_foreign_movements(record)


# --- Situations 4 to 6: constraints on a protection wish -----------------------------


def test_situation_4_a_storm_with_an_open_terrace_door() -> None:
    """No movement while the door is open; closes when it is shut."""
    record = run_named("storm-door-open").record

    assert reasons(first_decision(record, at(14))) == (
        ReasonCode.PROTECTION_EVENT,
        ReasonCode.LOCKOUT_DOOR_OPEN,
        None,
    )
    assert sends(record)[0] == ("14:30:00", 0, "protection_event")
    assert_no_intermediate_position(record, WINDOW, at(14), at(16))


def test_situation_5_the_tamper_contact_withdraws_the_trust_in_the_door() -> None:
    """Closes at once: ``lockout_void_tamper`` / ``sent``."""
    record = run_named("storm-door-tamper").record

    assert reasons(first_decision(record, at(14))) == (
        ReasonCode.PROTECTION_EVENT,
        ReasonCode.LOCKOUT_VOID_TAMPER,
        ReasonCode.SENT,
    )
    assert sends(record)[0] == ("14:00:00", 0, "protection_event")


def test_situation_6_hail_in_a_sleeping_room_marked_for_the_exception() -> None:
    """Stays closed: ``protection_event`` / ``sleep_exception_no_open`` / —."""
    record = run_named("hail-sleep-exception").record

    assert reasons(first_decision(record, at(2))) == (
        ReasonCode.PROTECTION_EVENT,
        ReasonCode.SLEEP_EXCEPTION_NO_OPEN,
        None,
    )
    assert not record.commands(WINDOW)


# --- Situations 7 to 10: the dams and the return ---------------------------------------


def test_situation_7_a_wall_button_during_a_storm_stands_for_fifteen_minutes() -> None:
    """First ``person_at_window``, then the storm position and a reason event."""
    record = run_named("person-at-window").record

    held = first_decision(record, at(14, 10, 0.7))
    assert reasons(held) == (ReasonCode.PROTECTION_EVENT, ReasonCode.PERSON_AT_WINDOW)
    restored = first_decision(record, at(14, 25, 0.7))
    assert reasons(restored) == (ReasonCode.PROTECTION_EVENT, ReasonCode.SENT)
    assert event_codes(record, ReasonCode.PERSON_AT_WINDOW_ENDED) == [
        ReasonCode.PERSON_AT_WINDOW_ENDED
    ]
    assert ("14:25:00", 0, "protection_event") in [
        (moment[:8], target, reason) for moment, target, reason in sends(record)
    ]


def test_situations_8_and_9_an_override_a_storm_and_the_return() -> None:
    """8: the storm closes, the override stays; 9: the person's 40 after the wait."""
    simulation = run_named("storm-return")
    record = simulation.record

    storm = first_decision(record, at(14))
    assert reasons(storm) == (ReasonCode.PROTECTION_EVENT, ReasonCode.SENT)
    during = decisions(record, at(14), at(14, 59))
    assert all(
        decision.winning_wish is not None
        and decision.winning_wish.reason is ReasonCode.PROTECTION_EVENT
        for decision in during
    )
    waiting = first_decision(record, at(15))
    assert waiting.winning_wish is not None
    assert waiting.winning_wish.kind is WishKind.LEAVE_ALONE
    back = first_decision(record, at(15, 30))
    assert reasons(back) == (ReasonCode.PROTECTION_RETURN_MANUAL, ReasonCode.SENT)
    assert sends(record) == [
        ("14:00:00", 0, "protection_event"),
        ("15:30:00", PERSON_LOWERS, "protection_return_manual"),
    ]
    assert event_codes(record, ReasonCode.OVERRIDE_ENDED) == []
    assert_dams_follow_foreign_movements(record)


def test_a_hand_movement_in_the_waiting_time_is_remembered_at_the_next_storm() -> None:
    """The review's case: the window returns to the person's 60, not to 40 or 0."""
    record = run_named("storm-twice").record

    starts = record.events(WINDOW, ReasonCode.PROTECTION_STARTED)
    assert [entry.at for entry in starts] == [at(14), at(15, 15)]
    assert sends(record) == [
        ("14:00:00", 0, "protection_event"),
        ("15:15:00", 0, "protection_event"),
        ("16:15:00", PERSON_OPENS, "protection_return_manual"),
    ]
    assert_dams_follow_foreign_movements(record)


def test_situation_10_the_override_expired_the_window_is_recomputed() -> None:
    """Whatever layer wins now: the schedule's day position."""
    record = run_named("storm-override-expired").record

    after = first_decision(record, at(15, 30))
    assert reasons(after) == (ReasonCode.SCHEDULE_DAY, ReasonCode.SENT)
    assert sends(record)[-1] == ("15:30:00", 100, "schedule_day")


# --- Situation 14 and D6 --------------------------------------------------------------


def test_situation_14_the_source_is_away_the_event_holds_and_is_reported_blind() -> (
    None
):
    """Input held; blind once after an hour; the end comes with the returning value."""
    record = run_named("storm-source-away").record

    held = decisions(record, at(14, 30), at(16, 29))
    assert held
    for decision in held:
        assert decision.winning_wish is not None
        assert decision.winning_wish.reason is ReasonCode.PROTECTION_EVENT
    blind = record.events(WINDOW, ReasonCode.PROTECTION_SOURCE_BLIND)
    assert [entry.at for entry in blind] == [at(15, 30)]
    assert blind[0].event is not None
    assert blind[0].event.event_id == "storm"
    subject = decisions(record, at(15, 30), at(15, 31))[0].winning_wish
    assert subject is not None
    assert subject.subject is not None
    assert subject.subject.held is ReasonCode.INPUT_HELD_LAST_KNOWN
    assert event_codes(record, ReasonCode.PROTECTION_ENDED) == [
        ReasonCode.PROTECTION_ENDED
    ]
    assert sends(record) == [
        ("14:00:00", 0, "protection_event"),
        ("17:00:00", 100, "schedule_day"),
    ]
    assert_no_intermediate_position(record, WINDOW, at(14), at(17))


# --- The watchdog, two events, fire during a storm ------------------------------------


def test_the_watchdog_releases_a_stuck_source_and_re_arms_after_one_off() -> None:
    """Released at 13:00; effective again at 14:30 after being off from 14:00."""
    record = run_named("storm-stuck").record

    assert [
        entry.at for entry in record.events(WINDOW, ReasonCode.WATCHDOG_RELEASED)
    ] == [at(13)]
    released = first_decision(record, at(13))
    watchdog = [e for e in released.other_layers if e.layer.value == "protection"]
    assert watchdog[0].reason is ReasonCode.WATCHDOG_RELEASED
    assert sends(record) == [
        ("13:00:00", 100, "schedule_day"),
        ("14:30:00", 0, "protection_event"),
        ("16:00:00", 100, "schedule_day"),
    ]


def test_two_events_at_once_the_higher_rank_wins_and_an_active_one_outranks() -> None:
    """Hail opens over the storm; after the hail the active storm closes again."""
    record = run_named("storm-and-hail").record

    assert sends(record) == [
        ("14:00:00", 0, "protection_event"),
        ("14:30:00", 100, "protection_event"),
        ("14:45:00", 0, "protection_event"),
        ("16:30:00", 100, "schedule_day"),
    ]
    hail = first_decision(record, at(14, 30))
    assert hail.winning_wish is not None
    assert hail.winning_wish.subject is not None
    assert hail.winning_wish.subject.event_id == "hail"
    assert_no_intermediate_position(record, WINDOW, at(14), at(16))


def test_fire_during_a_storm_wins_and_the_storm_applies_after_the_acknowledgement() -> (
    None
):
    """Fire opens unstaggered; unacknowledged it holds; acknowledged, the storm closes."""
    record = run_named("fire-during-storm").record

    assert sends(record) == [
        ("14:00:00", 0, "protection_event"),
        ("14:30:00", 100, "fire_alarm"),
        ("15:00:00", 0, "protection_event"),
        ("16:30:00", 100, "schedule_day"),
    ]
    held = decisions(record, at(14, 40), at(14, 59))
    assert held
    assert all(
        reasons(decision) == (ReasonCode.FIRE_UNACKNOWLEDGED, None) for decision in held
    )


# --- Restarts: the same subsequent commands ------------------------------------------


def _commands(record: Record) -> list[tuple[str, str | None, int | None]]:
    return [
        (
            entry.at.isoformat(timespec="milliseconds"),
            entry.member_id,
            None if entry.target is None else entry.target.value,
        )
        for entry in record.commands()
    ]


@pytest.mark.parametrize("restart", list(PROTECTION_RESTARTS))
def test_a_restart_during_the_event_or_its_waiting_time_changes_no_command(
    restart: str,
) -> None:
    """During the storm, during the waiting time, after the return."""
    reference = storm_return_with_restart(None)
    reference.run(reference.now + timedelta(hours=6))
    interrupted = storm_return_with_restart(restart)
    interrupted.run(interrupted.now + timedelta(hours=6))

    assert interrupted.restarts == 1
    assert interrupted.record.of_kind(EntryKind.RESTART)
    assert _commands(interrupted.record) == _commands(reference.record)
    assert_no_command_loop(interrupted.record)


@pytest.mark.parametrize("restart", [time(13, 30), time(14, 15)])
def test_a_restart_during_a_release_changes_no_command(restart: time) -> None:
    """Released, and released after the trigger was off once: the same commands."""
    reference = storm_stuck_with_restart(None)
    reference.run(reference.now + timedelta(days=1))
    interrupted = storm_stuck_with_restart(restart)
    interrupted.run(interrupted.now + timedelta(days=1))

    assert interrupted.restarts == 1
    assert _commands(interrupted.record) == _commands(reference.record)


def test_the_real_layers_replace_the_stubs_of_the_simulation() -> None:
    """The default arbiter of a simulation is the one of the integration."""
    simulation = run_named("storm")
    engine = simulation.window(WINDOW).engine

    functions = {entry.function for entry in engine.arbiter.layers}
    assert {value.value for value in functions if value is not None} >= {
        "fire",
        "protection_events",
        "schedule",
    }
