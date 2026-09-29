"""The movement tracker and the dams in the time-lapse simulation (block C06).

Every behaviour profile of the simulated cover with an own movement, a hand
movement, a stop in mid-travel, a dropout with the same and with another
position, and a reversal; the polled platform with four members commanded at
once; two members side by side with one moved by hand; every end of the
manual override; the person at the window during a storm; a window in
dry-run next to a second controller for a whole day; and restarts during a
movement, a settle time and an armed dam. Every run is judged with the
assertions of the simulation, and with the one this block adds: no own
movement ever arms a dam.
"""

import inspect
from datetime import datetime, time, timedelta
from typing import Final

import pytest

from custom_components.roller_shutter_suite.core.model import (
    Position,
    PositionOwner,
    PositionReference,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.sim import runner as runner_module
from tests.sim.assertions import (
    ARMING,
    assert_dams_follow_foreign_movements,
    assert_no_command_loop,
    assert_no_commands,
)
from tests.sim.record import Entry, Record
from tests.sim.runner import Simulation
from tests.sim.scenarios import (
    MONDAY,
    MORNING,
    OTHER_CONTROLLER,
    OVERRIDE_ENDS,
    PERSON_CHOOSES,
    PROFILES,
    RESTART_POINTS,
    TRACKING_CASES,
    dry_run_whole_day,
    hand_movement_with_restart,
    local,
    override_end,
    own_movement_with_restart,
    pair_one_by_hand,
    person_at_window,
    polled_four,
    profile_case,
)

WINDOW: Final = "window_example"
FIVE_HOURS: Final = timedelta(hours=5)
TRANSIT: Final = frozenset(
    name for name, profile in PROFILES.items() if profile.transit_states
) - {"no_position"}
"""The profiles whose covers report "opening" and "closing"."""


def _run(simulation: Simulation, length: timedelta) -> Record:
    record = simulation.run(simulation.now + length)
    assert_no_command_loop(record)
    assert_dams_follow_foreign_movements(record)
    return record


def _arming(record: Record, window_id: str = WINDOW) -> list[Entry]:
    return record.events(window_id, *ARMING)


def _codes(record: Record, window_id: str = WINDOW) -> list[ReasonCode]:
    return [
        entry.event.code
        for entry in record.events(window_id)
        if entry.event is not None
    ]


# --- Every profile, every case ----------------------------------------------------------


@pytest.mark.parametrize("profile", sorted(set(PROFILES) - {"no_position"}))
def test_an_own_command_is_the_integrations_movement_and_arms_no_dam(
    profile: str,
) -> None:
    """The morning opening: attributed to the integration, whatever the cover reports."""
    simulation = profile_case(profile, "own")
    record = _run(simulation, FIVE_HOURS)
    state = simulation.window(WINDOW).state

    assert record.events(WINDOW) == []
    assert state.owner is PositionOwner.ENGINE
    assert state.manual_override is None
    assert state.person_at_window is None
    assert state.members[0].position_reference is PositionReference.REFERENCED
    measured = state.members[0].self_measurement
    event_driven = PROFILES[profile].report_delay_for_the_core == timedelta(0)
    assert len(measured.latency_ms) == (1 if event_driven else 0)


@pytest.mark.parametrize("profile", sorted(set(PROFILES) - {"no_position"}))
def test_a_hand_movement_arms_the_override_with_the_persons_position(
    profile: str,
) -> None:
    """At 09:00 a person lowers the window to 40; the override remembers it."""
    simulation = profile_case(profile, "hand")
    record = _run(simulation, FIVE_HOURS)
    state = simulation.window(WINDOW).state

    assert [e.event.code for e in _arming(record) if e.event is not None] == [
        ReasonCode.MANUAL_DETECTED,
        ReasonCode.MANUAL_DETECTED_MEMBER,
        ReasonCode.OVERRIDE_STARTED,
    ]
    assert state.owner is PositionOwner.USER
    override = state.manual_override
    assert override is not None
    assert override.remembered_position is not None
    # A measured position settles one short in the direction of travel.
    assert abs(override.remembered_position.value - 40) <= 1
    assert len(record.sends(WINDOW)) == 1  # the morning; the override holds


def test_events_raised_at_the_start_of_a_movement_carry_no_position() -> None:
    """``end_only`` keeps the old position during the travel (section 8.3).

    The movement is detected at its first transit state, when the cover
    still reports 100: the events carry no position rather than the one the
    person left. The dam remembers the position once the movement has come
    to rest.
    """
    simulation = profile_case("end_only", "hand")
    record = _run(simulation, FIVE_HOURS)
    override = simulation.window(WINDOW).state.manual_override

    positions = [e.event.position for e in _arming(record) if e.event is not None]
    assert positions == [None, None, None]
    assert override is not None
    assert override.remembered_position == Position(40)


def test_events_raised_at_rest_carry_the_position_the_person_chose() -> None:
    """Without transit states a movement is judged at rest, where it stands."""
    simulation = profile_case("no_transit", "hand")
    record = _run(simulation, FIVE_HOURS)

    positions = [e.event.position for e in _arming(record) if e.event is not None]
    assert positions == [Position(40)] * 3


@pytest.mark.parametrize("profile", sorted(set(PROFILES) - {"no_position"}))
def test_a_stop_in_mid_travel_is_external_and_the_position_uncertain(
    profile: str,
) -> None:
    """A person stops the morning opening halfway; a cover without stop ignores it."""
    simulation = profile_case(profile, "stop")
    record = _run(simulation, FIVE_HOURS)
    state = simulation.window(WINDOW).state

    if profile == "no_stop":
        assert record.events(WINDOW) == []
        assert state.manual_override is None
        return
    assert ReasonCode.OVERRIDE_STARTED in _codes(record)
    assert ReasonCode.POSITION_MAY_BE_INACCURATE in _codes(record)
    assert state.members[0].position_reference is PositionReference.UNCERTAIN
    override = state.manual_override
    assert override is not None
    assert override.remembered_position is not None
    assert 0 < override.remembered_position.value < 100  # noqa: PLR2004 - halfway


@pytest.mark.parametrize("profile", sorted(set(PROFILES) - {"no_position"}))
def test_a_dropout_that_ends_in_the_same_observation_changes_nothing(
    profile: str,
) -> None:
    """The cover returns with the state it had."""
    simulation = profile_case(profile, "dropout_same")
    record = _run(simulation, FIVE_HOURS)
    state = simulation.window(WINDOW).state

    assert record.events(WINDOW) == []
    assert state.owner is PositionOwner.ENGINE
    assert state.manual_override is None


@pytest.mark.parametrize("profile", sorted(set(PROFILES) - {"no_position"}))
def test_a_dropout_that_ends_with_another_position_reads_moved_during_downtime(
    profile: str,
) -> None:
    """It counts as external; the position may be inaccurate."""
    simulation = profile_case(profile, "dropout_moved")
    record = _run(simulation, FIVE_HOURS)
    state = simulation.window(WINDOW).state

    assert _codes(record)[:2] == [
        ReasonCode.MOVED_DURING_DOWNTIME,
        ReasonCode.POSITION_MAY_BE_INACCURATE,
    ]
    assert state.manual_override is not None
    assert state.owner is PositionOwner.USER


@pytest.mark.parametrize("profile", sorted(TRANSIT))
def test_a_reversal_is_external_before_the_movement_ends(profile: str) -> None:
    """Four seconds into the opening a person sends the cover down again."""
    simulation = profile_case(profile, "reversal")
    record = _run(simulation, FIVE_HOURS)
    first = _arming(record)[0]

    assert first.at < MORNING + PROFILES[profile].travel_time_up
    assert simulation.window(WINDOW).state.manual_override is not None


def test_without_transit_states_a_reversal_is_judged_at_the_deadline() -> None:
    """A member that reports rest only cannot show a reversal as such.

    During the expectation its reports are attributed to the own command
    until the evaluation (section 8.3); it ends far from its target, so at
    the deadline it is external all the same.
    """
    simulation = profile_case("no_transit", "reversal")
    record = _run(simulation, FIVE_HOURS)
    first = _arming(record)[0]

    assert first.at > MORNING + PROFILES["no_transit"].travel_time_up
    assert simulation.window(WINDOW).state.manual_override is not None


def test_on_a_polled_platform_a_reversal_within_one_poll_is_invisible() -> None:
    """The cover is back where it started before its first report: no reaction.

    What a polled platform reports cannot tell a reversal inside one grid
    interval from an actuator that did not react; the tracker says only
    what it can know. The command is sent again once the minimum interval
    has passed; command verification and its backoff (block H15) own what
    follows.
    """
    simulation = profile_case("polled", "reversal")
    record = simulation.run(simulation.now + FIVE_HOURS)

    assert_dams_follow_foreign_movements(record)
    assert _codes(record) == [ReasonCode.ACTUATOR_NO_REACTION]
    assert simulation.window(WINDOW).state.manual_override is None
    assert [e.at - MORNING for e in record.sends(WINDOW)] == [
        timedelta(0),
        timedelta(minutes=10),
    ]


@pytest.mark.parametrize("case", TRACKING_CASES)
def test_a_member_without_position_feedback_has_no_manual_detection(case: str) -> None:
    """Section 8.1: no tracking, no manual detection, whatever happens to it."""
    simulation = profile_case("no_position", case)
    record = _run(simulation, FIVE_HOURS)

    assert record.events(WINDOW) == []
    assert simulation.window(WINDOW).state.manual_override is None


def test_the_blocked_curtain_is_the_integrations_movement() -> None:
    """A calculated position reports the target although the curtain stopped at 60."""
    simulation = profile_case("blocked", "own")
    record = _run(simulation, FIVE_HOURS)
    cover = simulation.world.cover("cover.example_window")

    assert cover.real_position(simulation.now) == 60  # noqa: PLR2004 - blocked at 60
    assert record.events(WINDOW) == []
    assert simulation.window(WINDOW).state.manual_override is None


# --- The polled platform with four members --------------------------------------------


def test_four_polled_members_commanded_at_once_raise_nothing() -> None:
    """No false manual detection, no "no reaction" for a member that reported in time."""
    simulation = polled_four()
    record = _run(simulation, timedelta(hours=16))

    assert record.events(WINDOW) == []
    commands = record.commands(WINDOW)
    assert len(commands) == 8  # noqa: PLR2004 - four members, morning and evening
    state = simulation.window(WINDOW).state
    assert all(member.tracking.phase.value == "idle" for member in state.members)


# --- Two members, one moved by hand (decision 8) ------------------------------------------


def test_one_member_moved_by_hand_holds_the_whole_window() -> None:
    """The right member stays; at the evening boundary both are brought to their target."""
    simulation = pair_one_by_hand()
    record = _run(simulation, timedelta(hours=15))
    started = record.events(WINDOW, ReasonCode.OVERRIDE_STARTED)
    ended = record.events(WINDOW, ReasonCode.OVERRIDE_ENDED)
    member_events = record.events(WINDOW, ReasonCode.MANUAL_DETECTED_MEMBER)

    assert len(started) == 1
    assert [e.member_id for e in member_events] == ["cover.example_left"]
    held = [e for e in record.commands(WINDOW) if started[0].at < e.at < ended[0].at]
    assert held == []
    right = simulation.world.cover("cover.example_right")
    assert right.commands == [(ended[0].at, 0, "engine")]
    after = [e for e in record.commands(WINDOW) if e.at >= ended[0].at]
    assert {e.member_id for e in after} == {"cover.example_left", "cover.example_right"}
    assert all(e.at == ended[0].at for e in after)


# --- Every end of the manual override ------------------------------------------------------


def _ended(how: str) -> tuple[Record, datetime, datetime]:
    simulation = override_end(how)
    record = _run(simulation, timedelta(hours=11))
    (started,) = record.events(WINDOW, ReasonCode.OVERRIDE_STARTED)
    (ended,) = record.events(WINDOW, ReasonCode.OVERRIDE_ENDED)
    return record, started.at, ended.at


@pytest.mark.parametrize(
    ("how", "ends"),
    [
        ("room_empty", time(11, 30)),
        ("resume", time(11, 0)),
        ("sleep_mode", time(11, 0)),
    ],
)
def test_the_override_ends_at_the_instant_of_its_rule(how: str, ends: time) -> None:
    """Thirty minutes after the room became empty; the button; sleep mode."""
    record, _, ended = _ended(how)

    assert ended == local(MONDAY, ends)
    sends = [e for e in record.sends(WINDOW) if e.at >= ended]
    assert sends[0].at == ended
    assert sends[0].target == Position(100)


def test_fixed_minutes_end_thirty_minutes_after_the_arming() -> None:
    """The dam was armed when the person's movement was seen, not when it ended."""
    record, started, ended = _ended("fixed_minutes")

    assert ended == started + timedelta(minutes=30)
    assert next(e.at for e in record.sends(WINDOW) if e.at >= ended) == ended


def test_the_default_rule_ends_the_override_at_the_evening_boundary() -> None:
    """A room darkened by hand stays dark until the evening, and then closes."""
    record, _, ended = _ended("next_part_of_day")
    decision = next(
        e.decision for e in record.sends(WINDOW) if e.at == ended and e.decision
    )

    assert ended.astimezone(record.zone).time() > time(19, 0)
    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.SCHEDULE_NIGHT


def test_every_end_of_the_override_has_a_scenario() -> None:
    """Resume and sleep mode are ends as well as the three rules the sim can script."""
    assert set(OVERRIDE_ENDS) == {
        "fixed_minutes",
        "next_part_of_day",
        "room_empty",
        "resume",
        "sleep_mode",
    }


# --- The person at the window during a storm -------------------------------------------------


def test_the_person_at_the_window_holds_the_storm_and_protection_returns_after() -> (
    None
):
    """The storm lasts beyond the dam: after 15 minutes protection closes again."""
    simulation = person_at_window(time(15, 0))
    record = _run(simulation, timedelta(hours=3))
    (started,) = record.events(WINDOW, ReasonCode.PERSON_AT_WINDOW_STARTED)
    (ended,) = record.events(WINDOW, ReasonCode.PERSON_AT_WINDOW_ENDED)

    assert ended.at == started.at + timedelta(minutes=15)
    during = [e for e in record.commands(WINDOW) if started.at <= e.at < ended.at]
    assert during == []
    at_the_end = [e for e in record.commands(WINDOW) if e.at == ended.at]
    assert [e.target for e in at_the_end] == [Position(0)]
    assert at_the_end[0].wish_class is not None
    assert at_the_end[0].wish_class.value == "protection"
    assert record.events(WINDOW, ReasonCode.OVERRIDE_STARTED) == []


def test_after_the_storm_the_dam_turns_into_an_override_with_the_persons_position() -> (
    None
):
    """The storm ends first: the person's 60 stands until the evening boundary."""
    simulation = person_at_window(time(14, 20))
    record = _run(simulation, timedelta(hours=8))
    (ended,) = record.events(WINDOW, ReasonCode.PERSON_AT_WINDOW_ENDED)
    (override,) = record.events(WINDOW, ReasonCode.OVERRIDE_STARTED)
    (over,) = record.events(WINDOW, ReasonCode.OVERRIDE_ENDED)

    assert override.at == ended.at
    assert override.event is not None
    assert override.event.position == Position(PERSON_CHOOSES)
    held = [e for e in record.commands(WINDOW) if ended.at <= e.at < over.at]
    assert held == []
    assert over.at.astimezone(record.zone).time() > time(19, 0)


# --- A window in dry-run next to a second controller ------------------------------------------


def test_a_window_in_dry_run_observes_every_foreign_movement_once_and_arms_nothing() -> (
    None
):
    """A whole day: no dam, the owner stays unknown, one event per foreign movement."""
    simulation = dry_run_whole_day()
    record = _run(simulation, timedelta(days=1))
    state = simulation.window(WINDOW).state

    assert _codes(record) == [ReasonCode.EXTERNAL_MOVEMENT_OBSERVED] * len(
        OTHER_CONTROLLER
    )
    for (at, _), entry in zip(OTHER_CONTROLLER, record.events(WINDOW), strict=True):
        assert local(MONDAY, at) <= entry.at < local(MONDAY, at) + timedelta(minutes=1)
    assert state.manual_override is None
    assert state.person_at_window is None
    assert state.owner is PositionOwner.UNKNOWN
    assert_no_commands(record, WINDOW)


# --- Restarts ----------------------------------------------------------------------------


def _after(record: Record, since: datetime) -> list[tuple[str, str | None, str]]:
    commands = [
        (e.at.isoformat(), e.member_id, e.summary)
        for e in record.commands(WINDOW)
        if e.at >= since
    ]
    events = [
        (e.at.isoformat(), e.member_id, e.summary)
        for e in record.events(WINDOW)
        if e.at >= since
    ]
    return commands + events


@pytest.mark.parametrize("restart", sorted(RESTART_POINTS))
def test_a_restart_around_a_hand_movement_changes_nothing_that_follows(
    restart: str,
) -> None:
    """During the movement, during its settle time, with the dam armed."""
    reference = _run(hand_movement_with_restart(None), timedelta(hours=12))
    interrupted = hand_movement_with_restart(restart)
    record = _run(interrupted, timedelta(hours=12))
    since = local(MONDAY, RESTART_POINTS[restart])

    assert interrupted.restarts == 1
    assert _after(record, since) == _after(reference, since)
    assert len(record.events(WINDOW, ReasonCode.MANUAL_DETECTED)) == 1


@pytest.mark.parametrize(
    "restart",
    [time(7, 0, 5), time(7, 0, 21), time(7, 0, 23)],
    ids=["in mid-movement", "while settling", "after settling"],
)
def test_a_restart_around_an_own_movement_detects_nothing_and_sends_nothing_again(
    restart: time,
) -> None:
    """The pending command, its expectation and its settle time survive the restart."""
    reference = _run(own_movement_with_restart(None), FIVE_HOURS)
    interrupted = own_movement_with_restart(restart)
    record = _run(interrupted, FIVE_HOURS)

    assert _after(record, local(MONDAY, restart)) == _after(
        reference, local(MONDAY, restart)
    )
    assert record.events(WINDOW) == []
    assert len(record.commands(WINDOW)) == 1


# --- Every time comes from the core --------------------------------------------------------


def test_the_runner_asks_the_core_for_every_wake_up() -> None:
    """The runner computes no time of its own; it reads ``Engine.wake_ups``."""
    source = inspect.getsource(runner_module)

    assert "member_expectation_end" not in source
    assert "SETTLE_TIME" not in source
    assert ".wake_ups(" in source
