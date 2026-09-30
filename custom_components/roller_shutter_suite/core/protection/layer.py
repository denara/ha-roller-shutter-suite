"""Layer 2: the protection events (D1, D2, D8; sections 2.1 and 10).

The layer judges every trigger live from the snapshot, with the life cycle
of :mod:`.events`, so it agrees with what ``Engine.elapse`` persists. Its
answer, in this order:

1. **An active event** that is not released, the highest rank first: the end
   position of its direction, class protection, reason ``protection_event``,
   with the event and its source as the subject (never inside the code). If
   the source has no value right now, the subject says why the input is held
   (situation 14).
2. **An event in its waiting time** that ended without a release: "leave
   alone" with ``waiting_for_delay`` and the event as the subject. The
   window stays where protection put it and no lower layer acts until the
   waiting time has passed (section 10.2), but nothing is driven against a
   person: the event has ended, so a movement by hand now arms the manual
   override, and a person-at-the-window dam that ends now turns into one
   (section 3.2). Active events outrank waiting ones.
3. **The return to the manual position** (decision 14), if it applies: a wish
   of class comfort with the reason ``protection_return_manual`` and the
   remembered position; its trigger is the end of the waiting time.
4. Otherwise **no opinion**: ``watchdog_released`` while a released event is
   still active, ``input_held_last_known`` (or ``input_unavailable``,
   ``input_unknown`` before the blind time) while a source has no value,
   ``inactive``, or ``not_configured`` without events.

An event whose stored direction is faulty is skipped (there is no cautious
direction). With a list that cannot be read as a whole, the layer holds the
window where it is ("leave alone", ``protection_event``) while a persisted
event is active or in its default waiting time, and has no opinion
otherwise (ruling of the project owner of 2026-10-01).
"""

from typing import Final

from custom_components.roller_shutter_suite.core.arbiter import LayerRegistration
from custom_components.roller_shutter_suite.core.model import (
    EVENTS_UNREADABLE,
    AnySourceValue,
    FunctionId,
    Layer,
    ProtectionEventConfig,
    ProtectionEventState,
    ProtectionEventStatus,
    WindowConfig,
    Wish,
    WishSubject,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode

from .blind import is_blind
from .events import (
    holds,
    holds_while_unreadable,
    live_states,
    return_applies,
    return_due,
    source_of,
    value_of,
    waiting,
)
from .trigger import missing_reason, read_trigger


def held_reason(
    config: WindowConfig,
    snapshot: WorldSnapshot,
    event: ProtectionEventConfig,
    state: ProtectionEventState,
) -> ReasonCode | None:
    """Return why the trigger of an event is held; ``None`` if it has a value.

    ``input_held_last_known`` once the source has had no value for the blind
    time, before that ``input_unavailable`` or ``input_unknown``.
    """
    value: AnySourceValue | None = value_of(event, snapshot.sources)
    if read_trigger(event.trigger, value).has_value:
        return None
    if event.trigger is None or is_blind(
        state.blind, now=snapshot.time, blind_after=config.source_blind_after
    ):
        return ReasonCode.INPUT_HELD_LAST_KNOWN
    return missing_reason(value)


def _subject(
    config: WindowConfig,
    snapshot: WorldSnapshot,
    event: ProtectionEventConfig,
    state: ProtectionEventState,
) -> WishSubject:
    return WishSubject(
        event_id=event.event_id,
        source=source_of(event),
        held=held_reason(config, snapshot, event, state),
    )


def _unreadable(snapshot: WorldSnapshot) -> Wish:
    for state in snapshot.state.protection_events:
        if holds_while_unreadable(state, snapshot.time):
            return Wish.leave_alone(
                Layer.PROTECTION, ReasonCode.PROTECTION_EVENT
            ).about(WishSubject(event_id=state.event_id))
    return Wish.no_opinion(Layer.PROTECTION, ReasonCode.INACTIVE)


def protection_layer(config: WindowConfig, snapshot: WorldSnapshot) -> Wish:
    """Return the wish of the protection events for the window."""
    events = config.protection_events
    if events is EVENTS_UNREADABLE:
        return _unreadable(snapshot)
    if not events:
        return Wish.no_opinion(Layer.PROTECTION, ReasonCode.NOT_CONFIGURED)
    now = snapshot.time
    states = live_states(config, snapshot, events)
    for event, state in states:
        if event.direction is not None and holds(event, state):
            return Wish.target(
                Layer.PROTECTION,
                ReasonCode.PROTECTION_EVENT,
                event.direction.end_position,
            ).about(_subject(config, snapshot, event, state))
    for event, state in states:
        if waiting(event, state, now):
            return Wish.leave_alone(
                Layer.PROTECTION, ReasonCode.WAITING_FOR_DELAY
            ).about(_subject(config, snapshot, event, state))
    for event, state in states:
        due = return_due(event, state)
        position = state.remembered_position
        if (
            due is not None
            and position is not None
            and return_applies(event, state, config, snapshot)
        ):
            return (
                Wish.target(
                    Layer.PROTECTION, ReasonCode.PROTECTION_RETURN_MANUAL, position
                )
                .triggered(due)
                .about(WishSubject(event_id=event.event_id, source=source_of(event)))
            )
    return _no_opinion(config, snapshot, states)


def _no_opinion(
    config: WindowConfig,
    snapshot: WorldSnapshot,
    states: tuple[tuple[ProtectionEventConfig, ProtectionEventState], ...],
) -> Wish:
    for event, state in states:
        if (
            event.direction is not None
            and state.status is ProtectionEventStatus.ACTIVE
            and state.released
        ):
            return Wish.no_opinion(
                Layer.PROTECTION, ReasonCode.WATCHDOG_RELEASED
            ).about(_subject(config, snapshot, event, state))
    for event, state in states:
        held = held_reason(config, snapshot, event, state)
        if held is not None:
            return Wish.no_opinion(Layer.PROTECTION, held).about(
                _subject(config, snapshot, event, state)
            )
    return Wish.no_opinion(Layer.PROTECTION, ReasonCode.INACTIVE)


PROTECTION_LAYER: Final = LayerRegistration(
    Layer.PROTECTION, protection_layer, function=FunctionId.PROTECTION_EVENTS
)
"""The protection layer; its function falls back on a fault and is never paused."""
