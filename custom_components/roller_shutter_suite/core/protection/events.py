"""The life cycle of a protection event: start, end, watchdog, waiting time, return.

The persisted state of each event (``ProtectionEventState``) holds times, not
deadlines; everything that depends on a setting (the waiting time, the
maximum duration, the blind time) is applied when it is evaluated, so a
changed setting takes effect at once and survives a restart (section 11).

- **Start.** The trigger becomes active: the event is active since now, its
  release is forgotten, and it remembers the position and the owner of the
  window and the manual override that is armed (section 10.2, decision 4).
  What an event remembered from an earlier activation, or what another event
  remembered, is taken over only while it still describes the window
  (:func:`still_remembers`): the other event holds the window; or the event
  is in its waiting time, the override in force is still the one it
  remembered and no person has taken the window since; or its return
  applies. Otherwise the window is remembered afresh, so a person who moved
  the window during the waiting time is remembered at the next start.
- **End.** The trigger becomes inactive: the event ends now (``ended_at``);
  its release, if there was one, is kept.
- **Watchdog** (section 10.3, decision 10). An event that is active longer
  than its maximum duration is released for this activation at the instant
  its maximum was reached (``released_at``). The release lasts until the
  trigger has been genuinely inactive once; a source without a value does
  not end it, and only a new activation makes the event effective again.
  A maximum duration of zero switches the watchdog off. Not for fire.
- **Waiting time and return** (section 10.2, decision 14). The waiting time
  runs from the release if there was one, otherwise from the end
  (``return_clock_start``). Until it has passed, an event that ended without
  a release still holds its end position. After it, the remembered position
  is restored if the remembered owner was a person and the manual override
  that was armed at the start is still armed; otherwise the window is
  recomputed normally. When no return applies any more, the event forgets
  its end, its release and what it remembered.

Every function is pure; :func:`protection_after` is the protection part of
``Engine.elapse`` and returns the state and the events it raised.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from functools import cache

from custom_components.roller_shutter_suite.core.arbiter import (
    override_ended_by_condition,
)
from custom_components.roller_shutter_suite.core.model import (
    DEFAULT_MAX_DURATION,
    DEFAULT_WAITING_TIME,
    EVENTS_UNREADABLE,
    AnySourceValue,
    ManualOverrideDam,
    Position,
    PositionOwner,
    ProtectionEventConfig,
    ProtectionEventState,
    ProtectionEventStatus,
    TrackerEvent,
    Transition,
    WindowConfig,
    WindowState,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode

from .blind import advance_blind_clock, blind_wake_up
from .trigger import Reading, read_trigger


@dataclass(frozen=True, slots=True)
class Remembered:
    """What an event remembers when it starts: position, owner, and the override."""

    position: Position | None
    owner: PositionOwner
    override_armed_at: datetime | None


NOTHING_REMEMBERED = Remembered(None, PositionOwner.UNKNOWN, None)
"""For an evaluation that judges an event without starting it for real."""


def _nothing(_state: ProtectionEventState) -> Remembered:
    return NOTHING_REMEMBERED


def in_order_of_rank(
    events: tuple[ProtectionEventConfig, ...],
) -> tuple[ProtectionEventConfig, ...]:
    """Return the events from the highest rank down; a faulty rank comes last.

    Among events with a faulty rank the order of the list decides, so the
    order never depends on anything but the configuration.
    """
    indexed = sorted(
        enumerate(events),
        key=lambda item: (item[1].rank is None, -(item[1].rank or 0), item[0]),
    )
    return tuple(event for _, event in indexed)


def source_of(event: ProtectionEventConfig) -> str | None:
    """Return the key of the trigger source; ``None`` for a faulty trigger."""
    return None if event.trigger is None else event.trigger.source


def value_of(
    event: ProtectionEventConfig, sources: Mapping[str, AnySourceValue]
) -> AnySourceValue | None:
    """Return the value of the trigger source in the snapshot, if it has one."""
    source = source_of(event)
    return None if source is None else sources.get(source)


def release_due(
    event_max: ProtectionEventConfig | None, state: ProtectionEventState
) -> datetime | None:
    """Return when the watchdog releases the active event; ``None``: it does not.

    ``event_max`` is the event, or ``None`` for an event of a list that cannot
    be read, which is watched with the default maximum duration.
    """
    maximum = DEFAULT_MAX_DURATION if event_max is None else event_max.max_duration
    if (
        state.status is not ProtectionEventStatus.ACTIVE
        or state.released
        or not maximum
        or state.active_since is None
    ):
        return None
    return state.active_since + maximum


def _event(code: ReasonCode, event_id: str, source: str | None) -> TrackerEvent:
    return TrackerEvent(code, event_id=event_id, source=source)


def advance_event(  # noqa: PLR0913 - the event, its state, the source, the moment and two facts
    event: ProtectionEventConfig,
    persisted: ProtectionEventState | None,
    value: AnySourceValue | None,
    now: datetime,
    *,
    blind_after: timedelta,
    remember: Callable[[ProtectionEventState], Remembered],
) -> tuple[ProtectionEventState, tuple[TrackerEvent, ...]]:
    """Return the state of one event after this moment, and the events it raised.

    The watchdog is judged first, on the state as it was persisted, so a
    release that fell due before a late evaluation (after a restart) keeps
    its instant and its order before the end of the trigger. ``remember``
    says what an event that starts now remembers, given its persisted
    state; it is asked only then.
    """
    state = persisted if persisted is not None else ProtectionEventState(event.event_id)
    source = source_of(event)
    raised: list[TrackerEvent] = []
    released_at = release_due(event, state)
    if released_at is not None and released_at <= now:
        state = replace(state, released_at=released_at)
        raised.append(_event(ReasonCode.WATCHDOG_RELEASED, event.event_id, source))
    reading = read_trigger(event.trigger, value)
    clock, blind_due = advance_blind_clock(
        state.blind, has_value=reading.has_value, now=now, blind_after=blind_after
    )
    if clock != state.blind:
        state = replace(state, blind=clock)
    if blind_due:
        raised.append(
            _event(ReasonCode.PROTECTION_SOURCE_BLIND, event.event_id, source)
        )
    if reading is Reading.ACTIVE and state.status is ProtectionEventStatus.INACTIVE:
        remembered = remember(state)
        state = ProtectionEventState(
            event_id=event.event_id,
            status=ProtectionEventStatus.ACTIVE,
            active_since=now,
            remembered_position=remembered.position,
            remembered_owner=remembered.owner,
            override_armed_at=remembered.override_armed_at,
            blind=state.blind,
        )
        raised.append(_event(ReasonCode.PROTECTION_STARTED, event.event_id, source))
    elif reading is Reading.INACTIVE and state.status is ProtectionEventStatus.ACTIVE:
        state = replace(
            state,
            status=ProtectionEventStatus.INACTIVE,
            active_since=None,
            ended_at=now,
        )
        raised.append(_event(ReasonCode.PROTECTION_ENDED, event.event_id, source))
    return state, tuple(raised)


def override_in_force(
    config: WindowConfig, snapshot: WorldSnapshot
) -> ManualOverrideDam | None:
    """Return the manual override if it is armed and holds at this moment."""
    dam = snapshot.state.manual_override
    if dam is None:
        return None
    if dam.ends_at is not None and dam.ends_at <= snapshot.time:
        return None
    if override_ended_by_condition(config, snapshot):
        return None
    return dam


def holds(event: ProtectionEventConfig, state: ProtectionEventState) -> bool:
    """Return whether the event is active and effective: not released."""
    return (
        event.direction is not None
        and state.status is ProtectionEventStatus.ACTIVE
        and not state.released
    )


def waiting(
    event: ProtectionEventConfig, state: ProtectionEventState, now: datetime
) -> bool:
    """Return whether the event ended without a release and its waiting time runs."""
    return (
        event.direction is not None
        and state.status is ProtectionEventStatus.INACTIVE
        and state.ended_at is not None
        and not state.released
        and now < state.ended_at + event.waiting_time
    )


def return_due(
    event: ProtectionEventConfig, state: ProtectionEventState
) -> datetime | None:
    """Return when the waiting time after the end or the release has passed.

    ``None`` while the event holds the window, and for an event without a
    return phase. The waiting time is the one configured now.
    """
    start = state.return_clock_start
    if start is None or holds(event, state):
        return None
    return start + event.waiting_time


def return_applies(
    event: ProtectionEventConfig,
    state: ProtectionEventState,
    config: WindowConfig,
    snapshot: WorldSnapshot,
) -> bool:
    """Return whether the window returns to the remembered manual position now.

    Decision 14: the waiting time has passed (d), the remembered owner was a
    person and the remembered position is known, and the manual override
    that was armed when the event started is still armed (a). That the
    person-at-the-window dam holds the return back (b) and that every
    constraint applies to it (c) is the arbiter's part: the return is a
    comfort wish.
    """
    due = return_due(event, state)
    if event.direction is None or due is None or snapshot.time < due:
        return False
    if state.remembered_owner is not PositionOwner.USER:
        return False
    if state.remembered_position is None or state.override_armed_at is None:
        return False
    override = override_in_force(config, snapshot)
    return override is not None and override.armed_at == state.override_armed_at


def _afresh(config: WindowConfig, snapshot: WorldSnapshot) -> Remembered:
    """Return the window as it stands: position, owner, the override that holds."""
    tolerances = {m.member_id: m.capabilities.tolerance for m in config.members}
    override = override_in_force(config, snapshot)
    return Remembered(
        snapshot.window_position(tolerances),
        snapshot.state.owner,
        None if override is None else override.armed_at,
    )


def still_remembers(
    event: ProtectionEventConfig,
    state: ProtectionEventState,
    config: WindowConfig,
    snapshot: WorldSnapshot,
) -> bool:
    """Return whether what an event remembered still describes the window.

    - The event holds the window (active, not released): protection put the
      window where it stands, and a person who moved it since is held by the
      person-at-the-window dam, whose position does not replace the
      remembered one (section 3.2).
    - The event is in its waiting time, the override in force is still the
      one it remembered, and no person has taken the window since (the owner
      is not a person): nothing has moved the window since protection did.
    - Its return applies: the window is being restored to what it remembered.

    Otherwise, a released event whose window was recomputed or a waiting
    event whose window a person moved, the window is remembered afresh.
    """
    if holds(event, state) or return_applies(event, state, config, snapshot):
        return True
    if not waiting(event, state, snapshot.time):
        return False
    override = override_in_force(config, snapshot)
    in_force = None if override is None else override.armed_at
    return (
        in_force == state.override_armed_at
        and snapshot.state.owner is not PositionOwner.USER
    )


def _kept(state: ProtectionEventState) -> Remembered:
    return Remembered(
        state.remembered_position,
        state.remembered_owner or PositionOwner.UNKNOWN,
        state.override_armed_at,
    )


def _rememberer(
    config: WindowConfig,
    snapshot: WorldSnapshot,
    ranked: tuple[ProtectionEventConfig, ...],
) -> Callable[[ProtectionEventState], Remembered]:
    """Return what an event that starts now remembers, given its persisted state.

    Its own earlier values while they still describe the window; otherwise
    what another event that still describes the window remembered (highest
    rank first); otherwise the window as it stands now.
    """
    persisted = {state.event_id: state for state in snapshot.state.protection_events}
    by_id = {event.event_id: event for event in ranked}

    @cache
    def others() -> Remembered:
        for event in ranked:
            state = persisted.get(event.event_id)
            if state is not None and still_remembers(event, state, config, snapshot):
                return _kept(state)
        return _afresh(config, snapshot)

    def remember(own: ProtectionEventState) -> Remembered:
        event = by_id.get(own.event_id)
        if event is not None and still_remembers(event, own, config, snapshot):
            return _kept(own)
        return others()

    return remember


def _forget_the_return(state: ProtectionEventState) -> ProtectionEventState:
    return ProtectionEventState(event_id=state.event_id, blind=state.blind)


def live_states(
    config: WindowConfig,
    snapshot: WorldSnapshot,
    events: tuple[ProtectionEventConfig, ...],
) -> tuple[tuple[ProtectionEventConfig, ProtectionEventState], ...]:
    """Return the events of the window, highest rank first, with their state now.

    The state as :func:`protection_after` would persist it at the time of the
    snapshot, so the layer judges the trigger live and agrees with what the
    caller persists, whether or not ``Engine.elapse`` ran first.
    """
    persisted = {state.event_id: state for state in snapshot.state.protection_events}
    result = []
    for event in in_order_of_rank(events):
        state, _ = advance_event(
            event,
            persisted.get(event.event_id),
            value_of(event, snapshot.sources),
            snapshot.time,
            blind_after=config.source_blind_after,
            remember=_nothing,
        )
        result.append((event, state))
    return tuple(result)


def protection_after(config: WindowConfig, snapshot: WorldSnapshot) -> Transition:
    """Return the state with every protection event as it stands now, and the events.

    Starts, ends, releases and blind phases are persisted and raised
    (``protection_started``, ``protection_ended``, ``watchdog_released``,
    ``protection_source_blind``, each with the event and its source). An
    event whose waiting time has passed and whose return does not apply any
    more forgets its return phase. A persisted event that is no longer
    configured is dropped. With a list that cannot be read, only the
    watchdog runs, with the default maximum duration.
    """
    state = snapshot.state
    events = config.protection_events
    if events is EVENTS_UNREADABLE:
        return _unreadable_after(snapshot)
    ranked = in_order_of_rank(events)
    persisted = {item.event_id: item for item in state.protection_events}
    remember = _rememberer(config, snapshot, ranked)
    by_id: dict[str, ProtectionEventState] = {}
    raised: list[TrackerEvent] = []
    for event in ranked:
        after, event_raised = advance_event(
            event,
            persisted.get(event.event_id),
            value_of(event, snapshot.sources),
            snapshot.time,
            blind_after=config.source_blind_after,
            remember=remember,
        )
        raised.extend(event_raised)
        by_id[event.event_id] = after
    for event in ranked:
        after = by_id[event.event_id]
        due = return_due(event, after)
        if (
            after.status is ProtectionEventStatus.INACTIVE
            and due is not None
            and due <= snapshot.time
            and not return_applies(event, after, config, snapshot)
        ):
            by_id[event.event_id] = _forget_the_return(after)
    states = tuple(by_id[event.event_id] for event in events if event.event_id in by_id)
    if states == state.protection_events:
        return Transition(state, tuple(raised))
    return Transition(replace(state, protection_events=states), tuple(raised))


def _unreadable_after(snapshot: WorldSnapshot) -> Transition:
    """Release the events of a list that cannot be read, by the default maximum."""
    state = snapshot.state
    raised: list[TrackerEvent] = []
    states: list[ProtectionEventState] = []
    for item in state.protection_events:
        due = release_due(None, item)
        if due is not None and due <= snapshot.time:
            item = replace(item, released_at=due)  # noqa: PLW2901 - the state after the release
            raised.append(_event(ReasonCode.WATCHDOG_RELEASED, item.event_id, None))
        states.append(item)
    if not raised:
        return Transition(state)
    return Transition(replace(state, protection_events=tuple(states)), tuple(raised))


def holds_while_unreadable(state: ProtectionEventState, now: datetime) -> bool:
    """Return whether a persisted event holds the window while the list cannot be read.

    It holds while it is active and not released, or while it ended without
    a release and the default waiting time runs.
    """
    if state.status is ProtectionEventStatus.ACTIVE:
        return not state.released
    return (
        state.ended_at is not None
        and not state.released
        and now < state.ended_at + DEFAULT_WAITING_TIME
    )


def protection_wake_ups(config: WindowConfig, state: WindowState) -> set[datetime]:
    """Return the instants at which a protection event changes without a report.

    The release by the watchdog, the end of the waiting time after the end
    or the release, and the moment a source without a value is reported as
    blind. The caller wakes the window at each (``Engine.wake_ups``).
    """
    times: set[datetime] = set()
    events = config.protection_events
    if events is EVENTS_UNREADABLE:
        for item in state.protection_events:
            if (due := release_due(None, item)) is not None:
                times.add(due)
            if item.ended_at is not None and not item.released:
                times.add(item.ended_at + DEFAULT_WAITING_TIME)
        return times
    persisted = {item.event_id: item for item in state.protection_events}
    for event in events:
        known = persisted.get(event.event_id)
        if known is None:
            continue
        if (due := release_due(event, known)) is not None:
            times.add(due)
        if known.return_clock_start is not None:
            times.add(known.return_clock_start + event.waiting_time)
        if (blind := blind_wake_up(known.blind, config.source_blind_after)) is not None:
            times.add(blind)
    return times


def judge_event(
    config: WindowConfig, snapshot: WorldSnapshot, event_id: str
) -> ProtectionEventState | None:
    """Judge a persisted event against its live source; for the restart (block C12).

    An event whose source is unavailable stays what it was (D6); an event
    whose source reports active is active from now on (caught up), and it
    remembers the window as it stands. ``None`` if the window has no such
    event, or its list cannot be read (then nothing can be judged, and the
    persisted state stands as it is).
    """
    events = config.protection_events
    if events is EVENTS_UNREADABLE:
        return None
    ranked = in_order_of_rank(events)
    for event in ranked:
        if event.event_id != event_id:
            continue
        persisted = {item.event_id: item for item in snapshot.state.protection_events}
        state, _ = advance_event(
            event,
            persisted.get(event_id),
            value_of(event, snapshot.sources),
            snapshot.time,
            blind_after=config.source_blind_after,
            remember=_rememberer(config, snapshot, ranked),
        )
        return state
    return None
