"""The movement tracker: who moved a member, and what that means (section 8).

The runtime reduces a state of Home Assistant to an :class:`Observation`; the
core receives observations, never states. The tracker follows every member
of a window through ``idle`` → ``expecting`` → ``moving`` → ``settling`` →
``idle`` and judges every movement once: the integration's own, or
somebody else's. What it attributes wrongly either freezes the automation or
overrules a person, so the rules are those of section 8.3:

- **Normalizing** (section 8.2): an observation equal to the last one of the
  member is dropped. That removes an identical write, a rewrite of an
  unchanged state with a new change time, and an attribute-only write that
  the same resting state follows. Nothing is ever based on a change time.
- **Own command:** ``Engine.state_after_send`` sets the tracker to
  ``expecting`` with the command (``arbiter/sent.py``). The first report of a
  movement makes it ``moving``; a report of rest makes it ``settling``.
- **A report of rest is the end of a movement** when the member showed a
  transit state during it, or when it stands within the tolerance of the
  target. A member that reports no transit state (a polled platform, one that
  lost them under load) writes rest on every report, so such a report in
  between is attributed to the own command until the target is reached or
  the deadline has passed ("platforms without transit states", "members with
  a report delay").
- **Settling:** a movement is judged once, a settle time after the report of
  rest (``settle_time`` of the gate): within the tolerance of the target it is
  the own movement and the expectation is consumed; outside it somebody
  intervened, and it is external.
- **Deadline** (``member_expectation_end``): nothing seen by then is
  ``actuator_no_reaction``; a movement still under way is
  ``movement_not_finished``. Both go to command verification (block H15),
  never arm a dam and never change the owner of the position. A member
  without transit states that came to rest short of its target is judged at
  the deadline, as if it had settled there.
- **Reversal:** a transit state against the commanded direction during
  ``expecting`` or ``moving`` is external at once.
- **Idle:** a movement that starts in ``idle`` is external; so is a change of
  the position beyond the tolerance on a member that shows no transit state.
- **Unavailable gap:** a return with the same observation is nothing; a
  return with another position is ``moved_during_downtime`` and counts as
  external.
- **Context:** a user identifier on a report at the start of a foreign
  movement is kept as a hint for the diagnostics and never decides
  (guardrail 6); its absence proves nothing.
- **External movement** arms a dam (``core/dams``) and sets the owner of the
  position to ``user``; the events ``manual_detected`` (the window) and
  ``manual_detected_member`` (which member) are raised. One member moved by
  hand is a hand movement of the whole window (decision 8). **In dry-run**
  nothing is armed and nothing changes: a foreign movement raises
  ``external_movement_observed`` and nothing else.
- **Position reference** (section 8.4): ``uncertain`` after an own movement
  that was stopped or reversed from outside, after ``movement_not_finished``
  and after ``moved_during_downtime``, with one ``position_may_be_inaccurate``
  event when it turns; ``referenced`` again after any complete movement into
  an end position, whoever commanded it. Members without "set position" and
  members without position feedback keep ``referenced``. The flag changes no
  decision.
- **Self-measurement:** for every own movement that came to rest on a member
  whose position is reported event-driven (report delay zero): the latency
  to the first report, the time to the report of rest and the deviation from
  the target.

A member without position feedback has no tracking and no manual detection
(section 8.1). The glass calibration never enters the comparison: commanded
and reported positions are both on the motor scale.

Every function is pure: a state and an observation in, a state and events out.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Final

from .arbiter import member_expectation_end, settle_time
from .arbiter.capabilities import has_no_position_feedback
from .dams import (
    arm_after_external_movement,
    armed_since,
    update_remembered_position,
    window_position,
)
from .model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    CapabilityState,
    Decision,
    MemberConfig,
    MemberState,
    MemberTracking,
    MovementState,
    Observation,
    Position,
    PositionReference,
    TrackerEvent,
    TrackerPhase,
    Transition,
    TravelDirection,
    WindowConfig,
    WindowState,
)
from .reasons import ReasonCode

HINT_WINDOW: Final = timedelta(seconds=5)
"""How long after the start of a foreign movement a user identifier is a hint.

The context of a state change carries the caller for about five seconds and
is gone on the final report (section 8).
"""

_IDLE: Final = MemberTracking()


@dataclass(frozen=True, slots=True)
class _Context:
    """What every step of the tracker for one call needs to know."""

    config: WindowConfig
    member: MemberConfig
    now: datetime
    last_decision: Decision | None
    dry_run: bool
    user_id: str | None = None

    @property
    def tolerance(self) -> int:
        """Return the tolerance of the member."""
        return self.member.capabilities.tolerance


# --- Helpers ---------------------------------------------------------------------


def _differs(one: Position | None, other: Position | None, tolerance: int) -> bool:
    """Return whether two reported positions lie further apart than the tolerance."""
    return (
        one is not None
        and other is not None
        and abs(one.value - other.value) > tolerance
    )


def _near(position: Position | None, target: Position, tolerance: int) -> bool:
    """Return whether a reported position stands within tolerance of a target."""
    return position is not None and abs(position.value - target.value) <= tolerance


def _against(observation: Observation, direction: TravelDirection) -> bool:
    """Return whether a transit state runs against the commanded direction."""
    if direction is TravelDirection.UP:
        return observation.state is MovementState.MOVING_DOWN
    return observation.state is MovementState.MOVING_UP


def _has_reference(member: MemberConfig) -> bool:
    """Return whether the member can drift: it is set to positions and reports them."""
    profile = member.capabilities
    return not has_no_position_feedback(profile) and (
        profile.capability_state("supports_set_position") is not CapabilityState.MISSING
    )


def _referenced(
    config: MemberConfig, member: MemberState, reference: PositionReference
) -> tuple[MemberState, tuple[TrackerEvent, ...]]:
    """Return the member with its position reference, and the hint event if it turned."""
    if not _has_reference(config) or member.position_reference is reference:
        return member, ()
    events: tuple[TrackerEvent, ...] = ()
    if reference is PositionReference.UNCERTAIN:
        events = (
            TrackerEvent(
                ReasonCode.POSITION_MAY_BE_INACCURATE, member_id=member.member_id
            ),
        )
    return replace(member, position_reference=reference), events


def _idle_keeping_the_gap(tracking: MemberTracking) -> MemberTracking:
    """Return the idle tracking after a deadline, keeping what was seen before a gap.

    A deadline that passes while the member is unavailable ends the
    expectation, but not the gap: the observation before it is what the
    return is compared with, so a movement during the gap still reads
    ``moved_during_downtime`` (section 8.3, "Unavailable gap").
    """
    return MemberTracking(before_gap=tracking.before_gap)


def _without_position(events: tuple[TrackerEvent, ...]) -> tuple[TrackerEvent, ...]:
    """Return the events without a position: raised at the start of a movement.

    At its start a movement has not reached the position the person chooses,
    and a platform that reports the transit state before the position still
    reports where the movement began. The dam's remembered position is set
    when the movement comes to rest.
    """
    return tuple(replace(event, position=None) for event in events)


def _at_an_end(position: Position | None) -> bool:
    return position in (FULLY_OPEN, FULLY_CLOSED)


def _measured(
    context: _Context, member: MemberState, position: Position
) -> MemberState:
    """Return the member with one more sample of its self-measurement, if it is measured.

    Only a member whose position is reported event-driven is measured: a
    polled one reports up to a minute late, and its numbers would say nothing
    about the cover (ruling of the project owner for block C06).
    """
    command = member.last_own_command
    tracking = member.tracking
    if (
        context.member.capabilities.report_delay != timedelta(0)
        or command is None
        or tracking.moved_at is None
        or tracking.rested_at is None
    ):
        return member
    latency = max(
        0, round((tracking.moved_at - command.time) / timedelta(milliseconds=1))
    )
    rest = max(
        0, round((tracking.rested_at - command.time) / timedelta(milliseconds=1))
    )
    deviation = abs(position.value - command.target.value)
    return replace(
        member,
        self_measurement=member.self_measurement.with_sample(latency, rest, deviation),
    )


# --- An external movement ----------------------------------------------------------


def _detected(
    context: _Context,
    state: WindowState,
    member: MemberState,
    position: Position | None,
    *,
    tracking: MemberTracking = _IDLE,
) -> Transition:
    """Return the state after a movement was attributed to somebody else.

    In dry-run the event ``external_movement_observed`` and nothing else. For
    an armed window ``manual_detected`` (the window) and
    ``manual_detected_member`` (the member, with the hint of a user if there
    was one), and the dam the movement arms. ``tracking`` is what the tracker
    follows afterwards: nothing, or the rest of a movement that is detected
    while it is still under way (its start, or a reversal).

    The events of a movement that is detected while under way carry no
    position: it is not yet the position the person chooses, and a platform
    that reports the transit state first still reports where the movement
    began. The dam remembers the position once the movement has come to
    rest; the decision record shows it from then on. No second event.

    One movement of the window by hand arms its dam once (decision 8; the
    window is moving from the first member that moves until the last one has
    settled). A member that is detected while another member is still
    moving, or whose movement began before the dam was armed, belongs to the
    movement of the window that armed it: it raises ``manual_detected_member``
    and brings the remembered position up to date, and nothing else. On a
    member with a report delay the movement may have begun up to that delay
    before it was seen.
    """
    under_way = tracking.detected
    hint = member.tracking.user_hint
    member_event = TrackerEvent(
        ReasonCode.MANUAL_DETECTED_MEMBER,
        member_id=member.member_id,
        position=None if under_way else position,
        user_id=hint,
    )
    others_moving = replace(
        state,
        members=tuple(m for m in state.members if m.member_id != member.member_id),
    ).moving
    started = member.tracking.moved_at
    state = state.with_member(replace(member, tracking=tracking))
    if context.dry_run:
        return Transition(
            state, (replace(member_event, code=ReasonCode.EXTERNAL_MOVEMENT_OBSERVED),)
        )
    at = window_position(context.config, state)
    armed_at = armed_since(context.config, state)
    if armed_at is not None and (
        others_moving
        or (
            started is not None
            and armed_at >= started - context.member.capabilities.report_delay
        )
    ):
        return Transition(update_remembered_position(state, at), (member_event,))
    armed = arm_after_external_movement(
        context.config, state, context.now, context.last_decision, at
    )
    events = (
        TrackerEvent(ReasonCode.MANUAL_DETECTED, position=at),
        member_event,
        *armed.events,
    )
    return Transition(armed.state, _without_position(events) if under_way else events)


def _settled_external(
    context: _Context,
    state: WindowState,
    member: MemberState,
    position: Position | None,
) -> Transition:
    """Judge a foreign movement that has come to rest."""
    events: tuple[TrackerEvent, ...] = ()
    if not context.dry_run and _at_an_end(position):
        member, events = _referenced(
            context.member, member, PositionReference.REFERENCED
        )
    if member.tracking.detected:
        # Reported at its start already (a reversal): only the position the
        # person chose is brought up to date.
        state = state.with_member(replace(member, tracking=_IDLE))
        if not context.dry_run:
            state = update_remembered_position(
                state, window_position(context.config, state)
            )
        return Transition(state, events)
    detected = _detected(context, state, member, position)
    return Transition(detected.state, (*events, *detected.events))


# --- Judging an own movement ---------------------------------------------------------


def _settled_own(
    context: _Context, state: WindowState, member: MemberState, position: Position
) -> Transition:
    """Judge an own movement once, with the position reported by the end of settling."""
    command = member.last_own_command
    assert command is not None  # noqa: S101 - the model ties the tracker to the command
    member = _measured(context, member, position)
    if _near(position, command.target, context.tolerance):
        # The integration's own movement: the expectation is consumed.
        events: tuple[TrackerEvent, ...] = ()
        if _at_an_end(command.target):
            member, events = _referenced(
                context.member, member, PositionReference.REFERENCED
            )
        return Transition(state.with_member(replace(member, tracking=_IDLE)), events)
    # Somebody intervened: a stop, another command. External.
    reference = (
        PositionReference.REFERENCED
        if _at_an_end(position)
        else PositionReference.UNCERTAIN
    )
    member, events = _referenced(context.member, member, reference)
    detected = _detected(context, state, member, position)
    return Transition(detected.state, (*events, *detected.events))


def _reversed(
    context: _Context, state: WindowState, member: MemberState, observation: Observation
) -> Transition:
    """Judge a transit state against the commanded direction: external at once."""
    member, events = _referenced(context.member, member, PositionReference.UNCERTAIN)
    following = MemberTracking(
        phase=TrackerPhase.MOVING,
        external=True,
        detected=True,
        moved_at=member.tracking.moved_at or context.now,
        transit_seen=True,
        user_hint=member.tracking.user_hint,
    )
    detected = _detected(
        context, state, member, observation.position, tracking=following
    )
    return Transition(detected.state, (*events, *detected.events))


# --- Reports -------------------------------------------------------------------------


def _report_while_idle(
    context: _Context,
    state: WindowState,
    member: MemberState,
    previous: Observation | None,
    observation: Observation,
) -> Transition:
    """Follow a report while nothing is expected: a movement that starts here is external.

    With a transit state that is reliable at once (every movement has a
    start report), so the movement is reported and its dam armed at its
    start: protection must not close a shutter on a person who is still
    moving it. Its end brings the position the person chose up to date. A
    change of the position on a member without transit states is judged
    after its settle time.
    """
    if observation.moving:
        tracking = MemberTracking(
            phase=TrackerPhase.MOVING,
            external=True,
            moved_at=context.now,
            transit_seen=True,
            user_hint=context.user_id,
        )
        return _detected(
            context,
            state,
            replace(member, tracking=tracking),
            observation.position,
            tracking=replace(tracking, detected=True),
        )
    if previous is not None and _differs(
        previous.position, observation.position, context.tolerance
    ):
        tracking = MemberTracking(
            phase=TrackerPhase.SETTLING,
            external=True,
            moved_at=context.now,
            rested_at=context.now,
            user_hint=context.user_id,
        )
        return Transition(state.with_member(replace(member, tracking=tracking)))
    return Transition(state.with_member(member))


def _report_while_own(
    context: _Context,
    state: WindowState,
    member: MemberState,
    previous: Observation | None,
    observation: Observation,
) -> Transition:
    """Follow a report while an own command is expected, moving or settling."""
    command = member.last_own_command
    assert command is not None  # noqa: S101 - the model ties the tracker to the command
    tracking = member.tracking
    if observation.moving:
        if _against(observation, command.direction):
            return _reversed(context, state, member, observation)
        tracking = replace(
            tracking,
            phase=TrackerPhase.MOVING,
            moved_at=tracking.moved_at or context.now,
            transit_seen=True,
            rested_at=None,
        )
        return Transition(state.with_member(replace(member, tracking=tracking)))
    at_target = _near(observation.position, command.target, context.tolerance)
    if at_target or tracking.transit_seen:
        tracking = replace(
            tracking,
            phase=TrackerPhase.SETTLING,
            moved_at=tracking.moved_at or context.now,
            rested_at=context.now,
        )
        return Transition(state.with_member(replace(member, tracking=tracking)))
    changed = previous is None or previous.position != observation.position
    if changed or tracking.phase is TrackerPhase.SETTLING:
        # Rest in between on a member without transit states: still the own
        # command, until the target or the deadline.
        tracking = replace(
            tracking,
            phase=TrackerPhase.MOVING,
            moved_at=tracking.moved_at or context.now,
            rested_at=None,
        )
    return Transition(state.with_member(replace(member, tracking=tracking)))


def _report_while_external(
    context: _Context, state: WindowState, member: MemberState, observation: Observation
) -> Transition:
    """Follow a report while a foreign movement is under way or settling."""
    tracking = member.tracking
    if (
        tracking.user_hint is None
        and context.user_id is not None
        and tracking.moved_at is not None
        and context.now - tracking.moved_at <= HINT_WINDOW
    ):
        tracking = replace(tracking, user_hint=context.user_id)
    if observation.moving:
        tracking = replace(
            tracking, phase=TrackerPhase.MOVING, transit_seen=True, rested_at=None
        )
    else:
        tracking = replace(tracking, phase=TrackerPhase.SETTLING, rested_at=context.now)
    return Transition(state.with_member(replace(member, tracking=tracking)))


def _returned(
    context: _Context,
    state: WindowState,
    member: MemberState,
    before: Observation,
    observation: Observation,
) -> Transition | None:
    """Judge the return of an idle member from an unavailable gap; ``None``: go on.

    The same observation is nothing. So is a return at the target of the
    last own command, as in the restart reconciliation (section 11): an own
    movement whose deadline passed during the gap may have finished in it.
    Another position is ``moved_during_downtime``: the movement counts as
    external, and the position may be inaccurate. A member that returns
    moving is judged like any movement that starts in ``idle``.
    """
    if observation.moving:
        return None
    command = member.last_own_command
    if not _differs(before.position, observation.position, context.tolerance) or (
        command is not None
        and _near(observation.position, command.target, context.tolerance)
    ):
        return Transition(state.with_member(member))
    if context.dry_run:
        return _detected(context, state, member, observation.position)
    member, reference_events = _referenced(
        context.member, member, PositionReference.UNCERTAIN
    )
    detected = _detected(context, state, member, observation.position)
    return Transition(
        detected.state,
        (
            TrackerEvent(
                ReasonCode.MOVED_DURING_DOWNTIME,
                member_id=member.member_id,
                position=observation.position,
            ),
            *reference_events,
            *detected.events,
        ),
    )


def _report(
    context: _Context,
    state: WindowState,
    member: MemberState,
    previous: Observation | None,
    observation: Observation,
) -> Transition:
    """Follow a report of an available member, after the gap it may return from."""
    tracking = member.tracking
    if tracking.before_gap is not None:
        before = tracking.before_gap
        member = replace(member, tracking=replace(tracking, before_gap=None))
        previous = before
        if member.tracking.phase is TrackerPhase.IDLE:
            returned = _returned(context, state, member, before, observation)
            if returned is not None:
                return returned
    elif previous is not None and not previous.available:
        # Back from a gap that began before anything was seen of the member.
        return Transition(state.with_member(member))
    if member.tracking.follows_own_command:
        return _report_while_own(context, state, member, previous, observation)
    if member.tracking.external:
        return _report_while_external(context, state, member, observation)
    return _report_while_idle(context, state, member, previous, observation)


def observe(  # noqa: PLR0913 - the observation, its member, the time and the facts it is judged by
    config: WindowConfig,
    state: WindowState,
    member_id: str,
    observation: Observation,
    *,
    now: datetime,
    last_decision: Decision | None,
    dry_run: bool,
    user_id: str | None = None,
) -> Transition:
    """Return the state after one observation of a member, and the events it raised.

    An observation equal to the last one of the member is dropped: the same
    state object comes back, with no event. ``last_decision`` is the decision
    of the last recompute of the window: whether a protection wish is winning
    decides which dam an external movement arms. ``dry_run`` is whether the
    window is in dry-run. ``user_id`` is the user in the context of the
    report, if any; a hint, never a decision.
    """
    members = {member.member_id: member for member in config.members}
    member_config = members.get(member_id)
    member = state.member_state(member_id)
    previous = member.last_observation
    if member_config is None or observation == previous:
        return Transition(state)
    member = replace(member, last_observation=observation)
    if has_no_position_feedback(member_config.capabilities):
        return Transition(state.with_member(member))
    if not observation.available:
        tracking = member.tracking
        if previous is not None and previous.available and tracking.before_gap is None:
            tracking = replace(tracking, before_gap=previous)
        return Transition(state.with_member(replace(member, tracking=tracking)))
    context = _Context(config, member_config, now, last_decision, dry_run, user_id)
    return _report(context, state, member, previous, observation)


# --- Time passing: settling and the deadline ---------------------------------------------


def _settle_due(
    context: _Context, state: WindowState, member: MemberState
) -> Transition:
    """Judge a member whose settle time has passed; otherwise change nothing.

    A member that went away while settling is judged when it returns. An own
    movement whose report of rest carries no position cannot be judged: it
    waits for the next report, and at its deadline it is not finished.
    """
    tracking = member.tracking
    observation = member.last_observation
    assert tracking.rested_at is not None  # noqa: S101 - the model ties rest to settling
    if (
        tracking.rested_at + settle_time(context.member, tracking) > context.now
        or observation is None
        or not observation.available
    ):
        return Transition(state)
    if not tracking.follows_own_command:
        return _settled_external(context, state, member, observation.position)
    if observation.position is not None:
        return _settled_own(context, state, member, observation.position)
    command = member.last_own_command
    assert command is not None  # noqa: S101 - the model ties the tracker to the command
    if member_expectation_end(context.member, command) > context.now:
        return Transition(state)
    return _not_finished(context, state, member)


def _due(context: _Context, state: WindowState, member: MemberState) -> Transition:
    """Judge a member whose settle time or deadline has come; otherwise change nothing."""
    tracking = member.tracking
    if tracking.phase is TrackerPhase.SETTLING:
        return _settle_due(context, state, member)
    command = member.last_own_command
    if (
        not tracking.follows_own_command
        or command is None
        or member_expectation_end(context.member, command) > context.now
    ):
        return Transition(state)
    observation = member.last_observation
    if tracking.phase is TrackerPhase.EXPECTING:
        return Transition(
            state.with_member(
                replace(member, tracking=_idle_keeping_the_gap(tracking))
            ),
            (
                TrackerEvent(
                    ReasonCode.ACTUATOR_NO_REACTION, member_id=member.member_id
                ),
            ),
        )
    if (
        observation is not None
        and observation.position is not None
        and not observation.moving
        and not tracking.transit_seen
    ):
        # A member without transit states came to rest short of its target:
        # judged as if it had settled there.
        return _settled_own(context, state, member, observation.position)
    return _not_finished(context, state, member)


def _not_finished(
    context: _Context, state: WindowState, member: MemberState
) -> Transition:
    """Say ``movement_not_finished``: no rest that can be judged by the deadline."""
    member, events = _referenced(context.member, member, PositionReference.UNCERTAIN)
    return Transition(
        state.with_member(
            replace(member, tracking=_idle_keeping_the_gap(member.tracking))
        ),
        (
            TrackerEvent(ReasonCode.MOVEMENT_NOT_FINISHED, member_id=member.member_id),
            *events,
        ),
    )


def elapse(
    config: WindowConfig,
    state: WindowState,
    now: datetime,
    last_decision: Decision | None,
    *,
    dry_run: bool,
) -> Transition:
    """Return the state after the time has come to ``now``: settle times and deadlines.

    Every member whose settle time has passed is judged; every own command
    whose deadline has passed without a movement is ``actuator_no_reaction``,
    one whose movement has not come to rest ``movement_not_finished``.
    """
    events: list[TrackerEvent] = []
    for member_config in config.members:
        member = state.member_state(member_config.member_id)
        if member.tracking.phase is TrackerPhase.IDLE or has_no_position_feedback(
            member_config.capabilities
        ):
            continue
        context = _Context(config, member_config, now, last_decision, dry_run)
        step = _due(context, state, member)
        state = step.state
        events.extend(step.events)
    return Transition(state, tuple(events))


def position_uncertain(
    config: WindowConfig, state: WindowState, member_ids: tuple[str, ...]
) -> Transition:
    """Return the state with the position reference of members set to ``uncertain``.

    For the blocks that know of the other causes of drift: a frost phase, a
    frost waiver or a release by sun in which the member was moved (C10,
    C11). The hint event is raised once per member that turns.
    """
    events: list[TrackerEvent] = []
    for member_config in config.members:
        if member_config.member_id not in member_ids:
            continue
        member, raised = _referenced(
            member_config,
            state.member_state(member_config.member_id),
            PositionReference.UNCERTAIN,
        )
        if raised:
            state = state.with_member(member)
            events.extend(raised)
    return Transition(state, tuple(events))
