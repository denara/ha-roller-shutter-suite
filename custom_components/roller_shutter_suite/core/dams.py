"""Arming and ending the two dams (section 3 of the specification).

The gate only reads a dam (``arbiter/gate.py``); this module writes it.

- **Arming.** The tracker (``core/tracking``) calls
  :func:`arm_after_external_movement` when it attributes a movement to
  somebody else than the integration. While a protection wish is winning,
  the person-at-the-window dam is armed; otherwise the manual override dam,
  with the position the person chose. The arming reads the winning wish
  class of the last decision, so the protection layers of block C07 change
  nothing here. The owner of the position becomes ``user``. In dry-run
  nothing is ever armed; the tracker does not call this then.
- **Ending the manual override** (E2): after fixed minutes; when the shading
  episode it was armed during ends; at the next boundary between parts of
  the day (the default); after the room has been empty for the configured
  time; and at once through :func:`end_override`, which the "resume
  automation" button and action call (``Engine.resume``) and switching
  sleep mode on calls (``Engine.sleep_mode_switched_on``). The clock keeps
  running during a protection event (decision 4): every end is an instant
  or a condition, never a remaining duration.
- **Ending the person-at-the-window dam:** by itself after the configured
  time (default 15 minutes). If the protection event is still winning,
  protection reasserts itself through the recompute; if it has ended, the
  dam turns into a manual override dam with the person's position.

Every arming and every end raises its event (``override_started``,
``override_ended``, ``person_at_window_started``, ``person_at_window_ended``).
A rule that needs something the window lacks falls back to the default rule
at arming: "the shading episode ends" when no episode is running, and "the
room has been empty" without a readable presence source (none, or a faulty
one, which is configured, but blind) end at the next part of the day, so
that no override holds for ever and none ends earlier than the default
would.

Every function is pure: a state in, a state and events out.
"""

from dataclasses import replace
from datetime import datetime

from .arbiter import override_ended_by_condition
from .model import (
    Decision,
    ManualOverrideDam,
    MemberObservation,
    OverrideEndRule,
    PersonAtWindowDam,
    Position,
    PositionOwner,
    TrackerEvent,
    Transition,
    WindowConfig,
    WindowObservation,
    WindowState,
    WishClass,
    WorldSnapshot,
)
from .reasons import ReasonCode
from .schedule import ScheduleInputMissingError, evaluate_schedule


def window_position(config: WindowConfig, state: WindowState) -> Position | None:
    """Return the position of the window from the members' last observations.

    The rules of ``WindowObservation.position``: every member reports a
    position and they agree within tolerance. A member that has not been
    observed yet leaves the window without a position.
    """
    last = {member.member_id: member.last_observation for member in state.members}
    observed: list[MemberObservation] = []
    for member in config.members:
        observation = last.get(member.member_id)
        if observation is None:
            return None
        observed.append(MemberObservation(member.member_id, observation))
    tolerances = {
        member.member_id: member.capabilities.tolerance for member in config.members
    }
    return WindowObservation(tuple(observed)).position(tolerances)


def armed_since(config: WindowConfig, state: WindowState) -> datetime | None:
    """Return when the latest of the armed dams was armed; ``None`` without one.

    The person-at-the-window dam keeps its end only; it was armed its
    configured time before.
    """
    times = []
    if state.manual_override is not None:
        times.append(state.manual_override.armed_at)
    if state.person_at_window is not None:
        times.append(state.person_at_window.ends_at - config.person_at_window_duration)
    return max(times, default=None)


def protection_winning(decision: Decision | None) -> bool:
    """Return whether a protection wish won the decision; unknown counts as yes.

    Without a decision nobody knows whether a protection event is under way,
    and the person-at-the-window dam holds back more than the override: a
    person at the window is never overruled because a fact was missing.
    """
    if decision is None:
        return True
    wish = decision.winning_wish
    return wish is not None and wish.wish_class is WishClass.PROTECTION


def new_override(
    config: WindowConfig, state: WindowState, now: datetime, position: Position | None
) -> ManualOverrideDam:
    """Return a manual override dam armed now, by the configured end rule.

    "Fixed minutes" ends at an instant; "the next part of the day" gets its
    instant from the schedule (:func:`update_dams`); the two rules that end
    with a condition fall back to the next part of the day when the window
    cannot meet their condition at all.
    """
    settings = config.manual_override
    rule = settings.end_rule
    episode = state.shading_episode
    if rule is OverrideEndRule.SHADING_EPISODE_END and (
        episode is None or episode.active_since is None
    ):
        rule = OverrideEndRule.NEXT_PART_OF_DAY
    if rule is OverrideEndRule.ROOM_EMPTY and not isinstance(
        settings.presence_source, str
    ):
        rule = OverrideEndRule.NEXT_PART_OF_DAY
    return ManualOverrideDam(
        armed_at=now,
        end_rule=rule,
        ends_at=now + settings.minutes
        if rule is OverrideEndRule.FIXED_MINUTES
        else None,
        remembered_position=position,
    )


def arm_after_external_movement(
    config: WindowConfig,
    state: WindowState,
    now: datetime,
    last_decision: Decision | None,
    position: Position | None,
) -> Transition:
    """Return the state with the dam an external movement arms, and its event.

    While a protection wish is winning: the person-at-the-window dam, for the
    configured time. Otherwise the manual override dam. A dam that is armed
    already is armed again, with the new position and a new end; that is an
    arming too, and it raises its event. The owner of the position becomes
    ``user``.
    """
    if protection_winning(last_decision):
        dam = PersonAtWindowDam(
            ends_at=now + config.person_at_window_duration,
            remembered_position=position,
        )
        state = replace(state, person_at_window=dam, owner=PositionOwner.USER)
        code = ReasonCode.PERSON_AT_WINDOW_STARTED
    else:
        override = new_override(config, state, now, position)
        state = replace(state, manual_override=override, owner=PositionOwner.USER)
        code = ReasonCode.OVERRIDE_STARTED
    return Transition(state, (TrackerEvent(code, position=position),))


def update_remembered_position(
    state: WindowState, position: Position | None
) -> WindowState:
    """Return the state with the latest position a person chose in the armed dam.

    A movement that was reported at its start (a reversal) arms the dam
    before the person has finished; its end only brings the position up to
    date. The person-at-the-window dam is the one armed during a protection
    event, otherwise the manual override.
    """
    if state.person_at_window is not None:
        dam = replace(state.person_at_window, remembered_position=position)
        return replace(state, person_at_window=dam)
    if state.manual_override is not None:
        override = replace(state.manual_override, remembered_position=position)
        return replace(state, manual_override=override)
    return state


def end_override(state: WindowState) -> Transition:
    """End the manual override at once: "resume automation", or sleep mode switched on.

    Nothing is replayed: the window is recomputed. Without an armed override
    nothing changes and no event is raised.
    """
    if state.manual_override is None:
        return Transition(state)
    return Transition(
        replace(state, manual_override=None),
        (TrackerEvent(ReasonCode.OVERRIDE_ENDED),),
    )


def _next_boundary(
    config: WindowConfig, snapshot: WorldSnapshot, override: ManualOverrideDam
) -> tuple[bool, datetime | None]:
    """Say whether a boundary between parts of the day has passed since the arming.

    Otherwise return the next boundary, as far as the schedule can name it.
    While the schedule does not run for the window, nothing is known: the
    dam holds, with the end it has.
    """
    try:
        schedule = evaluate_schedule(config, snapshot)
    except ScheduleInputMissingError:
        return False, override.ends_at
    if schedule.part_of_day_since > override.armed_at:
        return True, None
    if schedule.next_action is None:
        return False, override.ends_at
    return False, schedule.next_action.at


def _override_after(
    config: WindowConfig, snapshot: WorldSnapshot, override: ManualOverrideDam
) -> ManualOverrideDam | None:
    """Return the override as it stands at the time of the snapshot; ``None``: ended."""
    now = snapshot.time
    if override.ends_at is not None and override.ends_at <= now:
        return None
    if override_ended_by_condition(config, snapshot):
        return None
    if override.end_rule is OverrideEndRule.NEXT_PART_OF_DAY:
        passed, ends_at = _next_boundary(config, snapshot, override)
        return None if passed else replace(override, ends_at=ends_at)
    if override.end_rule is OverrideEndRule.ROOM_EMPTY:
        source = config.override_presence_source
        value = None if not isinstance(source, str) else snapshot.sources.get(source)
        empty = value is not None and value.has_value and value.value is False
        if not empty:
            return replace(override, room_empty_since=None)
        if override.room_empty_since is None:
            return replace(override, room_empty_since=now)
    return override


def update_dams(
    config: WindowConfig, snapshot: WorldSnapshot, last_decision: Decision | None
) -> Transition:
    """Return the state with the dams as they stand at the time of the snapshot.

    Called before every recompute and at every wake-up of the window
    (``Engine.elapse``). A person-at-the-window dam whose time is up ends; if
    no protection wish won the last decision, it turns into a manual override
    with the person's position. A manual override whose end has come ends;
    one that ends at the next part of the day learns that instant from the
    schedule; one that ends with an empty room remembers since when the room
    has been seen empty.
    """
    state = snapshot.state
    now = snapshot.time
    events: list[TrackerEvent] = []
    person = state.person_at_window
    if person is not None and person.ends_at <= now:
        state = replace(state, person_at_window=None)
        events.append(TrackerEvent(ReasonCode.PERSON_AT_WINDOW_ENDED))
        if not protection_winning_after_the_dam(last_decision):
            converted = new_override(config, state, now, person.remembered_position)
            state = replace(state, manual_override=converted)
            events.append(
                TrackerEvent(
                    ReasonCode.OVERRIDE_STARTED, position=person.remembered_position
                )
            )
    armed = state.manual_override
    if armed is not None:
        at = snapshot if state is snapshot.state else replace(snapshot, state=state)
        after = _override_after(config, at, armed)
        if after != armed:
            state = replace(state, manual_override=after)
        if after is None:
            events.append(TrackerEvent(ReasonCode.OVERRIDE_ENDED))
    return Transition(state, tuple(events))


def protection_winning_after_the_dam(decision: Decision | None) -> bool:
    """Return whether protection still wins when the person-at-the-window dam ends.

    Unknown counts as "no": the dam then turns into a manual override with
    the person's position, which keeps what the person did from being undone
    by the comfort logic; a protection event that is still active passes
    that dam anyway.
    """
    return decision is not None and protection_winning(decision)
