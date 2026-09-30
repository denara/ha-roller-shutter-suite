"""The movement tracker, state transition by state transition (section 8.3).

``idle`` → ``expecting`` → ``moving`` → ``settling`` → ``idle``: every movement
is judged once, as the integration's own or as somebody else's. The tests
walk one window through reports and time with the driver of
``tests/core/tracking_kit.py``, the way the runtime does.
"""

from dataclasses import replace
from datetime import timedelta

import pytest

from custom_components.roller_shutter_suite.core.arbiter import (
    SETTLE_TIME,
    member_expectation_end,
)
from custom_components.roller_shutter_suite.core.model import (
    CommandResult,
    MemberState,
    MemberTracking,
    MovementState,
    Observation,
    OverrideEndRule,
    Position,
    PositionOwner,
    PositionReference,
    ReportingKind,
    SourceValue,
    TrackerPhase,
    TransitReporting,
    WindowState,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import LEFT, NOW, RIGHT, night, profile, storm, window
from tests.core.tracking_kit import (
    UNAVAILABLE,
    Driver,
    codes,
    driver,
    moving_down,
    moving_up,
    resting,
)

DETECTED = [
    ReasonCode.MANUAL_DETECTED,
    ReasonCode.MANUAL_DETECTED_MEMBER,
    ReasonCode.OVERRIDE_STARTED,
]


def _opening(subject: Driver, start: int = 0) -> None:
    """Report the member at ``start`` and let the stub schedule open it (to 100)."""
    subject.report(resting(start))
    decision = subject.recompute()
    assert decision.addressed == (LEFT,)
    assert _tracking(subject).phase is TrackerPhase.EXPECTING


def _tracking(subject: Driver, member: str = LEFT) -> MemberTracking:
    return subject.state.member_state(member).tracking


def _settle(subject: Driver, rested_at: float) -> None:
    subject.at(rested_at + SETTLE_TIME.total_seconds())
    subject.recompute()


# --- Normalizing --------------------------------------------------------------------


def test_an_observation_that_changes_nothing_is_dropped() -> None:
    """An identical write, a rewrite with a new change time: the same state comes back."""
    subject = driver()
    subject.report(resting(40))
    before = subject.state

    transition = subject.engine.observe(
        before, LEFT, resting(40), NOW + timedelta(minutes=20), None, dry_run=False
    )

    assert transition.state is before
    assert transition.events == ()


def test_an_observation_of_a_member_the_window_does_not_have_is_ignored() -> None:
    """The core knows the members of the window; anything else changes nothing."""
    subject = driver()
    transition = subject.engine.observe(
        subject.state, "cover.example_other", resting(3), NOW, None, dry_run=False
    )

    assert transition.state is subject.state


def test_the_first_observation_of_a_member_is_recorded_and_judges_nothing() -> None:
    """Nothing was known before, so nothing can have moved."""
    subject = driver()

    assert subject.report(resting(40)) == ()
    member = subject.state.member_state(LEFT)
    assert member.last_observation == resting(40)
    assert member.tracking == MemberTracking()


# --- The own movement ---------------------------------------------------------------


def test_an_own_movement_is_expected_moves_settles_and_is_consumed() -> None:
    """Transit states, rest at the target, the settle time: the integration's own."""
    subject = driver()
    _opening(subject)
    subject.at(0.7).report(moving_up(4))
    assert _tracking(subject).phase is TrackerPhase.MOVING
    subject.at(20).report(resting(100))
    assert _tracking(subject).phase is TrackerPhase.SETTLING

    subject.at(21).recompute()
    assert _tracking(subject).phase is TrackerPhase.SETTLING
    _settle(subject, 20)

    assert _tracking(subject) == MemberTracking()
    assert subject.events == []
    assert subject.state.owner is PositionOwner.ENGINE
    assert subject.state.manual_override is None
    measured = subject.state.member_state(LEFT).self_measurement
    assert measured.latency_ms == (700,)
    assert measured.rest_ms == (20000,)
    assert measured.deviation == (0,)


def test_rest_within_the_tolerance_of_the_target_is_the_own_movement() -> None:
    """A calculated position within 2 of the target stands there."""
    subject = driver()
    _opening(subject)
    subject.at(0.7).report(moving_up(4))
    subject.at(20).report(resting(98))
    _settle(subject, 20)

    assert subject.events == []
    assert subject.state.member_state(LEFT).self_measurement.deviation == (2,)


def test_a_position_written_shortly_after_rest_is_what_the_movement_is_judged_by() -> (
    None
):
    """Settling covers a platform that writes the position after the resting state."""
    subject = driver()
    _opening(subject)
    subject.at(0.7).report(moving_up(4))
    subject.at(20).report(resting(90))
    subject.at(20.5).report(resting(100))
    _settle(subject, 20.5)

    assert subject.events == []


def test_rest_in_between_without_transit_states_is_still_the_own_command() -> None:
    """A member that shows no transit state writes rest on every report."""
    subject = driver(
        profiles={LEFT: profile(reports_transit_states=TransitReporting.NO)}
    )
    _opening(subject)
    subject.at(2).report(resting(10))
    assert _tracking(subject).phase is TrackerPhase.MOVING
    subject.at(12).report(resting(60))
    subject.at(15).recompute()
    assert _tracking(subject).phase is TrackerPhase.MOVING
    subject.at(20).report(resting(100))
    assert _tracking(subject).phase is TrackerPhase.SETTLING
    _settle(subject, 20)

    assert subject.events == []
    assert _tracking(subject) == MemberTracking()


def test_a_report_of_rest_at_the_start_position_changes_nothing() -> None:
    """Nothing has happened yet: the tracker still expects the command."""
    subject = driver()
    _opening(subject, start=10)
    subject.report(Observation(MovementState.RESTING, Position(10)))

    assert _tracking(subject).phase is TrackerPhase.EXPECTING


# --- The deadline -------------------------------------------------------------------


def _deadline(subject: Driver) -> float:
    command = subject.state.member_state(LEFT).last_own_command
    assert command is not None
    end = member_expectation_end(subject.config.members[0], command)
    return (end - NOW).total_seconds()


def test_nothing_seen_by_the_deadline_is_no_reaction_and_arms_nothing() -> None:
    """``actuator_no_reaction``: for command verification, never manual operation."""
    subject = driver()
    _opening(subject)
    deadline = _deadline(subject)
    subject.at(deadline - 0.1).recompute()
    assert subject.events == []

    subject.at(deadline).recompute()

    assert codes(subject.events) == [ReasonCode.ACTUATOR_NO_REACTION]
    assert subject.events[0].member_id == LEFT
    assert subject.state.manual_override is None
    assert subject.state.person_at_window is None
    assert subject.state.owner is PositionOwner.ENGINE
    assert _tracking(subject) == MemberTracking()


def test_an_unavailable_member_at_the_deadline_did_not_react() -> None:
    """The member went away right after the command and never came back."""
    subject = driver()
    _opening(subject)
    subject.at(1).report(UNAVAILABLE)
    subject.at(_deadline(subject)).recompute()

    assert codes(subject.events) == [ReasonCode.ACTUATOR_NO_REACTION]


def test_a_movement_still_under_way_at_the_deadline_is_not_finished() -> None:
    """``movement_not_finished``: no dam, the owner stays, the position is uncertain."""
    subject = driver()
    _opening(subject)
    subject.at(0.7).report(moving_up(4))
    subject.at(_deadline(subject)).recompute()

    assert codes(subject.events) == [
        ReasonCode.MOVEMENT_NOT_FINISHED,
        ReasonCode.POSITION_MAY_BE_INACCURATE,
    ]
    assert subject.state.manual_override is None
    assert subject.state.owner is PositionOwner.ENGINE
    member = subject.state.member_state(LEFT)
    assert member.position_reference is PositionReference.UNCERTAIN
    assert member.tracking == MemberTracking()


def test_rest_short_of_the_target_without_transit_states_is_judged_at_the_deadline() -> (
    None
):
    """The member stopped in between and never reached the target: somebody stopped it."""
    subject = driver(
        profiles={LEFT: profile(reports_transit_states=TransitReporting.NO)}
    )
    _opening(subject)
    subject.at(4).report(resting(20))
    subject.at(10).report(resting(50))
    subject.at(_deadline(subject)).recompute()

    assert codes(subject.events) == [
        ReasonCode.POSITION_MAY_BE_INACCURATE,
        *DETECTED,
    ]
    assert subject.state.manual_override is not None
    assert subject.state.manual_override.remembered_position == Position(50)


# --- Somebody intervened ----------------------------------------------------------


def test_a_stop_in_mid_travel_is_external_and_the_position_uncertain() -> None:
    """Rest outside the tolerance after transit states: somebody stopped it."""
    subject = driver()
    _opening(subject)
    subject.at(0.7).report(moving_up(4))
    subject.at(10.7).report(resting(50))
    _settle(subject, 10.7)

    assert codes(subject.events) == [
        ReasonCode.POSITION_MAY_BE_INACCURATE,
        *DETECTED,
    ]
    assert subject.state.owner is PositionOwner.USER
    override = subject.state.manual_override
    assert override is not None
    assert override.remembered_position == Position(50)
    assert override.end_rule is OverrideEndRule.NEXT_PART_OF_DAY
    member = subject.state.member_state(LEFT)
    assert member.position_reference is PositionReference.UNCERTAIN
    assert member.self_measurement.deviation == (50,)


def test_a_reversal_is_external_at_once_and_its_end_updates_the_position() -> None:
    """A transit state against the commanded direction, before the movement ends."""
    subject = driver()
    _opening(subject)
    subject.at(0.7).report(moving_up(4))

    raised = subject.at(4.7).report(moving_down(16))

    assert codes(raised) == [ReasonCode.POSITION_MAY_BE_INACCURATE, *DETECTED]
    override = subject.state.manual_override
    assert override is not None
    assert override.remembered_position == Position(16)
    assert _tracking(subject).phase is TrackerPhase.MOVING
    assert _tracking(subject).detected
    subject.at(8).report(resting(0))
    _settle(subject, 8)

    assert codes(subject.events) == [ReasonCode.POSITION_MAY_BE_INACCURATE, *DETECTED]
    override = subject.state.manual_override
    assert override is not None
    assert override.remembered_position == Position(0)
    # A complete movement into an end position references the position again.
    member = subject.state.member_state(LEFT)
    assert member.position_reference is PositionReference.REFERENCED
    assert member.tracking == MemberTracking()


def test_a_reversal_before_any_report_is_external_too() -> None:
    """The first report already runs against the command."""
    subject = driver()
    _opening(subject, start=50)

    raised = subject.at(0.7).report(moving_down(48))

    assert ReasonCode.MANUAL_DETECTED in codes(raised)


def test_a_new_own_command_resets_the_expectation_as_a_whole() -> None:
    """A second command during travel replaces the first one's expectation."""
    subject = driver()
    _opening(subject)
    subject.at(0.7).report(moving_up(4))
    first = _tracking(subject).command_id
    subject.sources = storm()
    subject.at(2).recompute()

    tracking = _tracking(subject)
    assert tracking.phase is TrackerPhase.EXPECTING
    assert tracking.command_id != first
    assert tracking.moved_at is None


# --- A movement that starts in idle --------------------------------------------


def test_a_movement_that_starts_in_idle_is_external_at_once() -> None:
    """With a transit state it is reliable at its start; the end updates the position."""
    subject = driver()
    subject.report(resting(100))
    subject.recompute()

    raised = subject.at(1).report(moving_down(96), user_id="user-example")

    assert codes(raised) == DETECTED
    member_event = raised[1]
    assert member_event.member_id == LEFT
    assert member_event.user_id == "user-example"
    assert subject.state.owner is PositionOwner.USER
    subject.at(12).report(resting(40))
    _settle(subject, 12)
    override = subject.state.manual_override
    assert override is not None
    assert override.remembered_position == Position(40)
    assert codes(subject.events) == DETECTED


def test_a_position_change_in_idle_without_a_transit_state_is_judged_after_settling() -> (
    None
):
    """A member that shows no transit state is seen only through its reports of rest."""
    subject = driver()
    subject.report(resting(100))
    subject.at(2).report(resting(80), user_id="user-example")
    subject.at(4).report(resting(60))
    subject.at(5).recompute()
    assert subject.events == []
    _settle(subject, 4)

    assert codes(subject.events) == DETECTED
    assert subject.events[1].user_id == "user-example"
    assert subject.events[1].position == Position(60)


def test_a_hint_arrives_later_within_the_first_seconds() -> None:
    """The context carries the caller for about five seconds; later it proves nothing."""
    subject = driver()
    subject.report(resting(100))
    subject.at(2).report(resting(80))
    subject.at(4).report(resting(60), user_id="user-example")
    subject.at(9).report(resting(40), user_id="user-too-late")
    _settle(subject, 9)

    assert subject.events[1].user_id == "user-example"


def test_a_small_change_in_idle_within_the_tolerance_is_nothing() -> None:
    """A calculated position that moves by 2 has not been moved."""
    subject = driver()
    subject.report(resting(100))
    subject.recompute()
    subject.at(2).report(resting(98))
    _settle(subject, 2)

    assert subject.events == []
    assert _tracking(subject) == MemberTracking()


def test_on_a_member_with_a_report_delay_a_foreign_movement_settles_longer() -> None:
    """The next report can come a report delay later; the movement is judged once."""
    delay = timedelta(seconds=60)
    subject = driver(profiles={LEFT: profile(reporting_time=delay)})
    subject.report(resting(100))
    subject.at(60).report(resting(70))
    subject.at(70).recompute()
    assert subject.events == []
    subject.at(120).report(resting(40))
    subject.at(120 + 61).recompute()
    assert subject.events == []
    _settle(subject, 120 + delay.total_seconds())

    assert codes(subject.events) == DETECTED
    assert subject.events[1].position == Position(40)


# --- Which dam, and dry-run ------------------------------------------------------------


def test_a_movement_while_a_protection_wish_wins_arms_the_person_at_the_window_dam() -> (
    None
):
    """Guardrail 3: the storm does not close the shutter on a person."""
    subject = driver()
    subject.sources = storm()
    subject.report(resting(0))
    subject.recompute()
    subject.at(60).recompute()
    raised = subject.at(120).report(moving_up(4))

    assert codes(raised) == [
        ReasonCode.MANUAL_DETECTED,
        ReasonCode.MANUAL_DETECTED_MEMBER,
        ReasonCode.PERSON_AT_WINDOW_STARTED,
    ]
    dam = subject.state.person_at_window
    assert dam is not None
    assert dam.ends_at == NOW + timedelta(seconds=120, minutes=15)
    assert subject.state.manual_override is None
    decision = subject.at(130).recompute()
    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.PERSON_AT_WINDOW


def test_without_a_decision_the_person_at_the_window_dam_is_armed() -> None:
    """Nobody knows whether a protection event is under way; the person comes first."""
    subject = driver()
    subject.report(resting(100))
    subject.report(moving_down(96))

    assert subject.state.person_at_window is not None


def test_in_dry_run_a_foreign_movement_raises_one_event_and_changes_nothing_else() -> (
    None
):
    """No dam, no owner, no reference flag: the window next to a second controller."""
    subject = driver()
    subject.dry_run = True
    subject.report(resting(100))
    subject.recompute()
    subject.at(1).report(moving_down(96))
    subject.at(12).report(resting(40))
    _settle(subject, 12)
    subject.at(100).report(resting(70))
    _settle(subject, 100)

    assert codes(subject.events) == [
        ReasonCode.EXTERNAL_MOVEMENT_OBSERVED,
        ReasonCode.EXTERNAL_MOVEMENT_OBSERVED,
    ]
    assert subject.state.manual_override is None
    assert subject.state.person_at_window is None
    assert subject.state.owner is PositionOwner.UNKNOWN


def test_arming_a_window_forgets_a_movement_of_the_other_controller_under_way() -> None:
    """Arming starts clean: the other controller's movement is not taken for a person."""
    subject = driver()
    subject.dry_run = True
    subject.report(resting(100))
    subject.recompute()
    subject.at(1).report(moving_down(96))
    subject.at(2).report(resting(70))
    assert _tracking(subject).phase is TrackerPhase.SETTLING
    subject.dry_run = False
    subject.state = subject.engine.arm(subject.state)

    assert _tracking(subject) == MemberTracking()
    assert subject.state.member_state(LEFT).last_observation == resting(70)
    _settle(subject, 2)
    assert codes(subject.events) == [ReasonCode.EXTERNAL_MOVEMENT_OBSERVED]


# --- An unavailable gap --------------------------------------------------------------


def test_a_gap_that_ends_with_the_same_observation_is_nothing() -> None:
    """A cover returns with the state it had."""
    subject = driver()
    subject.report(resting(40))
    subject.at(10).report(UNAVAILABLE)
    assert _tracking(subject).before_gap == resting(40)
    subject.at(200).report(resting(40))

    assert subject.events == []
    assert _tracking(subject) == MemberTracking()


def test_a_gap_that_ends_with_another_position_is_moved_during_downtime() -> None:
    """It counts as external, and the position may be inaccurate."""
    subject = driver()
    subject.report(resting(100))
    subject.recompute()
    subject.at(10).report(UNAVAILABLE)
    raised = subject.at(300).report(resting(40))

    assert codes(raised) == [
        ReasonCode.MOVED_DURING_DOWNTIME,
        ReasonCode.POSITION_MAY_BE_INACCURATE,
        *DETECTED,
    ]
    assert subject.state.owner is PositionOwner.USER
    assert subject.state.manual_override is not None


def test_a_gap_that_ends_with_another_position_in_dry_run_is_only_observed() -> None:
    """In dry-run nothing but ``external_movement_observed``."""
    subject = driver()
    subject.dry_run = True
    subject.report(resting(100))
    subject.at(10).report(UNAVAILABLE)
    raised = subject.at(300).report(resting(40))

    assert codes(raised) == [ReasonCode.EXTERNAL_MOVEMENT_OBSERVED]
    assert subject.state.member_state(LEFT).position_reference is (
        PositionReference.REFERENCED
    )


def test_a_member_that_returns_moving_is_a_movement_that_starts_in_idle() -> None:
    """Its transit state is its start report."""
    subject = driver()
    subject.report(resting(100))
    subject.recompute()
    subject.at(10).report(UNAVAILABLE)
    raised = subject.at(300).report(moving_down(80))

    assert codes(raised) == DETECTED


def test_a_gap_during_an_own_movement_continues_the_expectation() -> None:
    """The report after the gap is judged against what was seen before it."""
    subject = driver()
    _opening(subject)
    subject.at(0.7).report(moving_up(4))
    subject.at(3).report(UNAVAILABLE)
    subject.at(8).report(moving_up(40))
    subject.at(20).report(resting(100))
    _settle(subject, 20)

    assert subject.events == []


def test_a_gap_in_the_middle_of_a_movement_without_transit_states_goes_on() -> None:
    """The member returns where it was before the gap: still the own command."""
    subject = driver(
        profiles={LEFT: profile(reports_transit_states=TransitReporting.NO)}
    )
    _opening(subject)
    subject.at(4).report(resting(20))
    subject.at(5).report(UNAVAILABLE)
    subject.at(6).report(resting(20))

    assert _tracking(subject).phase is TrackerPhase.MOVING
    subject.at(20).report(resting(100))
    _settle(subject, 20)
    assert subject.events == []


def test_rest_without_a_position_cannot_be_judged_and_is_not_finished_at_the_deadline() -> (
    None
):
    """A report of rest that carries no position: the tracker waits, then says so."""
    subject = driver()
    _opening(subject)
    subject.at(0.7).report(moving_up(4))
    subject.at(20).report(resting(None))
    _settle(subject, 20)
    assert subject.events == []
    assert _tracking(subject).phase is TrackerPhase.SETTLING

    subject.at(_deadline(subject)).recompute()

    assert codes(subject.events) == [
        ReasonCode.MOVEMENT_NOT_FINISHED,
        ReasonCode.POSITION_MAY_BE_INACCURATE,
    ]
    assert subject.state.manual_override is None


def _gap_spanning_the_deadline(subject: Driver, gone_at: float) -> float:
    """Let the member go away at ``gone_at`` and the deadline pass in the gap."""
    subject.at(gone_at).report(UNAVAILABLE)
    deadline = _deadline(subject)
    subject.at(deadline).recompute()
    return deadline


@pytest.mark.parametrize(
    ("phase", "deadline_event"),
    [
        (TrackerPhase.EXPECTING, ReasonCode.ACTUATOR_NO_REACTION),
        (TrackerPhase.MOVING, ReasonCode.MOVEMENT_NOT_FINISHED),
    ],
    ids=["expecting", "moving"],
)
def test_a_gap_that_spans_the_deadline_still_sees_a_movement_by_hand(
    phase: TrackerPhase, deadline_event: ReasonCode
) -> None:
    """The deadline ends the expectation, not the gap (section 8.3, "Unavailable gap").

    A wall button with a local link moves the cover while its link to the
    house is down: on its return the person is seen, and the next decision
    does not overrule them.
    """
    subject = driver()
    _opening(subject)
    if phase is TrackerPhase.MOVING:
        subject.at(0.7).report(moving_up(4))
    before = subject.observed[LEFT]
    assert _tracking(subject).phase is phase
    deadline = _gap_spanning_the_deadline(subject, 3)
    assert deadline_event in codes(subject.events)
    assert _tracking(subject) == MemberTracking(before_gap=before, ended_in_gap=True)

    raised = subject.at(deadline + 60).report(resting(40))

    assert ReasonCode.MOVED_DURING_DOWNTIME in codes(raised)
    assert codes(raised)[-3:] == DETECTED
    assert subject.state.manual_override is not None
    assert subject.state.owner is PositionOwner.USER
    decision = subject.at(deadline + 61).recompute()
    assert decision.addressed is None


def test_a_gap_that_spans_the_settle_time_judges_the_movement_on_return() -> None:
    """While settling the member waits for its return, deadline or not."""
    subject = driver()
    _opening(subject)
    subject.at(0.7).report(moving_up(4))
    subject.at(20).report(resting(100))
    deadline = _gap_spanning_the_deadline(subject, 20.5)
    assert subject.events == []
    assert _tracking(subject).phase is TrackerPhase.SETTLING

    subject.at(deadline + 60).report(resting(40))
    _settle(subject, deadline + 60)

    assert codes(subject.events)[-3:] == DETECTED
    assert subject.state.manual_override is not None
    assert subject.state.owner is PositionOwner.USER


@pytest.mark.parametrize("moved", [False, True], ids=["expecting", "moving"])
def test_a_return_at_the_own_target_after_the_deadline_is_nothing(
    *, moved: bool
) -> None:
    """The own movement may have finished during the gap, as at a restart."""
    subject = driver()
    _opening(subject)
    if moved:
        subject.at(0.7).report(moving_up(4))
    deadline = _gap_spanning_the_deadline(subject, 3)
    before = list(subject.events)

    assert subject.at(deadline + 60).report(resting(100)) == ()
    assert subject.events == before
    assert subject.state.manual_override is None
    assert subject.state.owner is PositionOwner.ENGINE


def test_a_return_at_the_old_target_after_a_gap_without_a_deadline_is_a_person() -> (
    None
):
    """The rule of the own target holds only for a gap in which a deadline ended.

    Carry-over from the review of C06: the own movement was judged before
    the gap, a person lowered the shutter, and during the gap somebody raised
    it to where the last own command had sent it. Nothing of the integration
    moved in the gap, so the return is somebody's movement.
    """
    subject = driver()
    _opening(subject)
    subject.at(0.7).report(moving_up(4))
    subject.at(20).report(resting(100))
    _settle(subject, 20)
    assert _tracking(subject) == MemberTracking()
    subject.at(100).report(moving_down(100))
    subject.at(110).report(resting(40))
    _settle(subject, 110)
    subject.at(200).report(UNAVAILABLE)
    assert _tracking(subject) == MemberTracking(before_gap=resting(40))

    raised = subject.at(300).report(resting(100))

    assert ReasonCode.MOVED_DURING_DOWNTIME in codes(raised)
    assert subject.state.owner is PositionOwner.USER


def test_the_flag_of_a_deadline_in_a_gap_needs_a_gap_and_survives_the_storage() -> None:
    """``ended_in_gap`` stands next to ``before_gap`` only; older data has none."""
    with pytest.raises(ValueError, match="only a gap"):
        MemberTracking(ended_in_gap=True)
    tracking = MemberTracking(before_gap=resting(40), ended_in_gap=True)
    assert MemberTracking.from_data(tracking.to_data()) == tracking
    older = tracking.to_data()
    del older["ended_in_gap"]
    assert MemberTracking.from_data(older) == MemberTracking(before_gap=resting(40))


def test_a_gap_that_starts_in_idle_is_unchanged_by_a_deadline() -> None:
    """The control case: no expectation, the return is compared with before."""
    subject = driver()
    subject.report(resting(100))
    subject.recompute()
    subject.at(10).report(UNAVAILABLE)
    subject.at(200).recompute()
    raised = subject.at(300).report(resting(40))

    assert codes(raised) == [
        ReasonCode.MOVED_DURING_DOWNTIME,
        ReasonCode.POSITION_MAY_BE_INACCURATE,
        *DETECTED,
    ]
    assert subject.state.owner is PositionOwner.USER


def test_a_gap_that_began_before_anything_was_seen_judges_nothing() -> None:
    """The member was never seen available: its first value is recorded."""
    subject = driver()
    subject.report(UNAVAILABLE)

    assert subject.report(resting(40)) == ()
    assert _tracking(subject) == MemberTracking()


# --- Members without tracking ---------------------------------------------------------


def test_a_member_without_position_feedback_has_no_tracking_and_no_detection() -> None:
    """Section 8.1: no tracking, no manual detection, no intermediate target."""
    subject = driver(profiles={LEFT: profile(reports_position=False)})
    subject.report(resting(None))
    subject.recompute()
    assert _tracking(subject) == MemberTracking()
    subject.at(5).report(Observation(MovementState.MOVING_DOWN))
    subject.at(30).report(resting(None))
    subject.at(200).recompute()

    assert subject.events == []
    assert subject.state.manual_override is None


def test_a_failed_command_is_not_expected_any_more() -> None:
    """The actuator never got it: nothing it reports is the integration's movement."""
    subject = driver()
    _opening(subject)
    command = subject.state.member_state(LEFT).last_own_command
    assert command is not None

    after = subject.engine.on_command_result(
        subject.state, CommandResult(command.command_id, LEFT, None, failed=True)
    )

    assert after.member_state(LEFT).tracking == MemberTracking()


def test_the_result_of_an_older_command_leaves_the_tracker_alone() -> None:
    """Only the command the tracker follows is dropped when it failed."""
    subject = driver()
    _opening(subject)

    after = subject.engine.on_command_result(
        subject.state, CommandResult("command-older", LEFT, None, failed=True)
    )

    assert after is subject.state


# --- The reference flag -------------------------------------------------------------


def test_a_complete_own_movement_into_an_end_position_references_again() -> None:
    """After an uncertain phase, the next opening to 100 counts from a known point."""
    subject = driver()
    subject.report(resting(0))
    subject.state = subject.state.with_member(
        replace(
            subject.state.member_state(LEFT),
            position_reference=PositionReference.UNCERTAIN,
        )
    )
    subject.recompute()
    subject.at(0.7).report(moving_up(4))
    subject.at(20).report(resting(100))
    _settle(subject, 20)

    assert subject.state.member_state(LEFT).position_reference is (
        PositionReference.REFERENCED
    )
    assert subject.events == []


@pytest.mark.parametrize(
    "changes",
    [{"supports_set_position": False}, {"reports_position": False}],
    ids=["no set position", "no position feedback"],
)
def test_members_that_cannot_drift_keep_their_reference(
    changes: dict[str, bool],
) -> None:
    """Members without "set position" or position feedback stay ``referenced``."""
    config = window(profiles={LEFT: profile(**changes)})
    subject = Driver(config)
    transition = subject.engine.position_uncertain(WindowState(), (LEFT,))

    assert transition.events == ()
    assert transition.state == WindowState()


def test_the_blocks_that_know_of_frost_can_make_a_position_uncertain_once() -> None:
    """The hint event is raised when the flag turns, not again."""
    subject = driver(LEFT, RIGHT)
    first = subject.engine.position_uncertain(WindowState(), (LEFT,))
    again = subject.engine.position_uncertain(first.state, (LEFT,))

    assert codes(first.events) == [ReasonCode.POSITION_MAY_BE_INACCURATE]
    assert first.events[0].member_id == LEFT
    assert first.state.member_state(LEFT).position_reference is (
        PositionReference.UNCERTAIN
    )
    assert first.state.member_state(RIGHT).position_reference is (
        PositionReference.REFERENCED
    )
    assert again.events == ()
    assert again.state is first.state


# --- The self-measurement ---------------------------------------------------------------


def test_a_polled_member_is_not_measured() -> None:
    """A polled member reports on its grid; its numbers say nothing."""
    polled = profile(
        reporting_kind=ReportingKind.POLLED, reporting_time=timedelta(seconds=8)
    )
    subject = driver(profiles={LEFT: polled})
    _opening(subject)
    subject.at(8.7).report(moving_up(4))
    subject.at(28).report(resting(100))
    _settle(subject, 28)

    assert subject.events == []
    assert subject.state.member_state(LEFT).self_measurement.latency_ms == ()


def test_an_event_driven_member_with_a_report_delay_is_measured() -> None:
    """Its latency is how a user finds the reporting time to state (2026-10-01)."""
    subject = driver(profiles={LEFT: profile(reporting_time=timedelta(seconds=8))})
    _opening(subject)
    subject.at(8.7).report(moving_up(4))
    subject.at(28).report(resting(100))
    _settle(subject, 28)

    assert subject.events == []
    assert subject.state.member_state(LEFT).self_measurement.latency_ms == (8700,)


def test_a_member_with_an_unknown_reporting_time_is_not_judged() -> None:
    """Unknown, never a guess of zero: no expectation, no event, no dam."""
    unknown = profile(reporting_kind=None, reporting_time=None)
    subject = driver(profiles={LEFT: unknown})
    subject.report(resting(0))
    assert subject.recompute().addressed == (LEFT,)
    assert subject.state.member_state(LEFT).last_own_command is not None
    assert subject.state.member_state(LEFT).tracking == MemberTracking()
    subject.at(200).recompute()
    assert subject.events == []

    # A movement nobody commanded is not judged either.
    subject.at(300).report(moving_down(100))
    subject.at(320).report(resting(40))
    _settle(subject, 320)
    assert subject.events == []
    assert subject.state.manual_override is None
    assert subject.state.member_state(LEFT).last_observation == resting(40)


def test_the_self_measurement_survives_as_persisted_data() -> None:
    """Ruling 2: persisted with the member state."""
    subject = driver()
    _opening(subject)
    subject.at(0.7).report(moving_up(4))
    subject.at(20).report(resting(100))
    _settle(subject, 20)

    assert WindowState.from_data(subject.state.to_data()) == subject.state


# --- Two members: one movement of the window -----------------------------------------


def test_one_member_moved_by_hand_arms_the_override_for_the_window() -> None:
    """Decision 8: both events, the window's and the member's; the other stays."""
    subject = driver(LEFT, RIGHT)
    subject.report(resting(100), LEFT)
    subject.report(resting(100), RIGHT)
    subject.recompute()

    raised = subject.at(1).report(moving_down(96), LEFT)

    assert codes(raised) == DETECTED
    assert raised[0].position is None  # the members no longer agree
    assert raised[1].member_id == LEFT
    decision = subject.at(5).recompute()
    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.MANUAL_OVERRIDE
    assert decision.addressed is None


def test_a_person_moving_every_member_arms_the_window_once() -> None:
    """The other members of the same movement raise their member event only."""
    subject = driver(LEFT, RIGHT)
    subject.report(resting(100), LEFT)
    subject.report(resting(100), RIGHT)
    subject.recompute()
    subject.at(1).report(moving_down(96), LEFT)
    subject.at(1.5).report(moving_down(97), RIGHT)
    subject.at(12).report(resting(40), LEFT)
    subject.at(13).report(resting(40), RIGHT)
    _settle(subject, 13)

    assert codes(subject.events) == [
        *DETECTED,
        ReasonCode.MANUAL_DETECTED_MEMBER,
    ]
    override = subject.state.manual_override
    assert override is not None
    assert override.remembered_position == Position(40)


def test_a_later_movement_by_hand_arms_the_override_again() -> None:
    """A new decision of the person: the dam is armed again, with a new end."""
    subject = driver(override_end_rule=OverrideEndRule.FIXED_MINUTES)
    subject.report(resting(100))
    subject.recompute()
    subject.at(1).report(moving_down(96))
    subject.at(12).report(resting(40))
    _settle(subject, 12)
    first = subject.state.manual_override
    assert first is not None
    subject.at(600).report(moving_up(44))

    assert codes(subject.events) == [*DETECTED, *DETECTED]
    second = subject.state.manual_override
    assert second is not None
    assert second.armed_at > first.armed_at
    assert second.ends_at is not None
    assert first.ends_at is not None
    assert second.ends_at > first.ends_at


def test_the_window_is_moving_until_the_last_member_has_settled() -> None:
    """While the tracker sees a member move, comfort waits, also without transit states."""
    subject = driver(
        profiles={LEFT: profile(reports_transit_states=TransitReporting.NO)}
    )
    subject.report(resting(100))
    subject.recompute()
    subject.at(2).report(resting(80))

    assert subject.state.moving
    subject.sources = night()
    decision = subject.at(3).recompute()
    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.MOVEMENT_IN_FLIGHT


def test_a_report_of_a_polled_member_later_in_the_same_movement_arms_nothing_again() -> (
    None
):
    """On a member with a report delay the movement may have begun that long before."""
    delay = timedelta(seconds=60)
    subject = driver(LEFT, RIGHT, profiles={RIGHT: profile(reporting_time=delay)})
    subject.report(resting(100), LEFT)
    subject.report(resting(100), RIGHT)
    subject.recompute()
    subject.at(1).report(moving_down(96), LEFT)
    subject.at(12).report(resting(40), LEFT)
    _settle(subject, 12)
    subject.at(60).report(resting(40), RIGHT)
    _settle(subject, 60 + delay.total_seconds())

    assert codes(subject.events) == [*DETECTED, ReasonCode.MANUAL_DETECTED_MEMBER]


def test_the_state_of_a_member_the_tracker_follows_matches_its_command() -> None:
    """The model ties the tracker to the last own command of the member."""
    with pytest.raises(ValueError, match="follows the last own command"):
        MemberState(
            LEFT,
            tracking=MemberTracking(phase=TrackerPhase.EXPECTING, command_id="c-1"),
        )


def test_a_person_at_the_window_during_a_storm_with_sources_of_the_kit() -> None:
    """The storm closes; a person opens it again: the storm waits for the person."""
    subject = driver()
    subject.sources = storm(part_of_day=SourceValue.of("day"))
    subject.report(resting(100))
    subject.recompute()
    subject.at(0.7).report(moving_down(96))
    subject.at(18).report(resting(0))
    _settle(subject, 18)
    assert subject.events == []
    raised = subject.at(300).report(moving_up(4))

    assert ReasonCode.PERSON_AT_WINDOW_STARTED in codes(raised)
