"""Layer 1: the fire alarm (D3; sections 2.1 and 2.4).

One fire source of the house, an on/off source (``WindowConfig.fire_source``).

- **While the alarm is active:** open fully, class fire, reason
  ``fire_alarm``, for every member, no intermediate target. The fire bypass
  of the gate applies; no constraint applies to fire.
- **After the alarm has ended and until a person acknowledges it:** "leave
  alone" with ``fire_unacknowledged``. It still wins, so it holds every lower
  layer back, but it moves nothing: after a false alarm the integration does
  not reopen a shutter that somebody closes by hand. The flag is set at every
  activation and cleared by :func:`acknowledge_fire` at any time (the action
  of block H07, the button of block H14), which raises ``fire_acknowledged``.
- **A source without a value changes nothing** (D6): an active alarm stays
  active, an inactive one stays inactive; ``WindowState.fire_alarm_active``
  holds the state the alarm had at its last value. After the blind time the
  layer says ``input_held_last_known`` and ``protection_source_blind`` is
  raised once, with the source and without an event identifier (ruling of the
  project owner of 2026-10-01: a fire source that goes blind is reported like
  a protection source). A fire source that is configured, but blind because
  its stored setting is faulty (``BLIND_SOURCE``), holds at once; the fault is
  reported by the resolver of the settings.

Not for fire: the watchdog, the return, the sleep-room exception, staggering,
frost. The layer judges the source live, as ``Engine.elapse`` persists it.
"""

from dataclasses import replace
from datetime import datetime
from typing import Final

from custom_components.roller_shutter_suite.core.arbiter import LayerRegistration
from custom_components.roller_shutter_suite.core.model import (
    FULLY_OPEN,
    AnySourceValue,
    FunctionId,
    Layer,
    ProtectionTrigger,
    TrackerEvent,
    Transition,
    WindowConfig,
    WindowState,
    Wish,
    WishSubject,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode

from .blind import advance_blind_clock, blind_wake_up, is_blind
from .trigger import Reading, missing_reason, read_trigger


def _reading(
    config: WindowConfig, snapshot: WorldSnapshot
) -> tuple[Reading, AnySourceValue | None]:
    source = config.fire_source
    if not isinstance(source, str):
        return Reading.UNKNOWN, None
    value = snapshot.sources.get(source)
    return read_trigger(ProtectionTrigger(source), value), value


def fire_alarm_active(config: WindowConfig, snapshot: WorldSnapshot) -> bool:
    """Return whether the fire alarm is active now; a silent source holds its state."""
    reading, _ = _reading(config, snapshot)
    if reading is Reading.ACTIVE:
        return True
    if reading is Reading.INACTIVE:
        return False
    return snapshot.state.fire_alarm_active


def _subject(config: WindowConfig, snapshot: WorldSnapshot) -> WishSubject:
    source = config.fire_source
    reading, value = _reading(config, snapshot)
    if not isinstance(source, str):
        return WishSubject(held=ReasonCode.INPUT_HELD_LAST_KNOWN)
    held = None
    if not reading.has_value:
        blind = is_blind(
            snapshot.state.fire_blind,
            now=snapshot.time,
            blind_after=config.source_blind_after,
        )
        held = ReasonCode.INPUT_HELD_LAST_KNOWN if blind else missing_reason(value)
    return WishSubject(source=source, held=held)


def fire_layer(config: WindowConfig, snapshot: WorldSnapshot) -> Wish:
    """Return the wish of the fire alarm for the window."""
    unacknowledged = snapshot.state.fire_unacknowledged
    if config.fire_source is None:
        if unacknowledged:
            return Wish.leave_alone(Layer.FIRE, ReasonCode.FIRE_UNACKNOWLEDGED)
        return Wish.no_opinion(Layer.FIRE, ReasonCode.NOT_CONFIGURED)
    subject = _subject(config, snapshot)
    if fire_alarm_active(config, snapshot):
        return Wish.target(Layer.FIRE, ReasonCode.FIRE_ALARM, FULLY_OPEN).about(subject)
    if unacknowledged:
        return Wish.leave_alone(Layer.FIRE, ReasonCode.FIRE_UNACKNOWLEDGED).about(
            subject
        )
    if subject.held is not None:
        return Wish.no_opinion(Layer.FIRE, subject.held).about(subject)
    return Wish.no_opinion(Layer.FIRE, ReasonCode.INACTIVE).about(subject)


def fire_after(config: WindowConfig, snapshot: WorldSnapshot) -> Transition:
    """Return the state with the fire alarm as it stands now, and the events.

    An activation sets the held state and ``fire_unacknowledged``; an end
    clears the held state only. The clock of a source without a value runs,
    and the blind source is reported once per blind phase.
    """
    state = snapshot.state
    source = config.fire_source
    events: list[TrackerEvent] = []
    clock = None
    if isinstance(source, str):
        reading, _ = _reading(config, snapshot)
        clock, due = advance_blind_clock(
            state.fire_blind,
            has_value=reading.has_value,
            now=snapshot.time,
            blind_after=config.source_blind_after,
        )
        if due:
            events.append(
                TrackerEvent(ReasonCode.PROTECTION_SOURCE_BLIND, source=source)
            )
    active = (
        state.fire_alarm_active
        if source is None
        else fire_alarm_active(config, snapshot)
    )
    after = replace(
        state,
        fire_alarm_active=active,
        fire_unacknowledged=state.fire_unacknowledged
        or (active and not state.fire_alarm_active),
        fire_blind=clock,
    )
    if after == state:
        return Transition(state, tuple(events))
    return Transition(after, tuple(events))


def acknowledge_fire(state: WindowState) -> Transition:
    """Acknowledge the fire alarm: the recompute falls through to the lower layers.

    It can be done at any time. Without an unacknowledged alarm nothing
    changes and no event is raised.
    """
    if not state.fire_unacknowledged:
        return Transition(state)
    return Transition(
        replace(state, fire_unacknowledged=False),
        (TrackerEvent(ReasonCode.FIRE_ACKNOWLEDGED),),
    )


def fire_wake_ups(config: WindowConfig, state: WindowState) -> set[datetime]:
    """Return the instant at which the fire source is reported as blind, if any."""
    due = blind_wake_up(state.fire_blind, config.source_blind_after)
    return set() if due is None else {due}


FIRE_LAYER: Final = LayerRegistration(Layer.FIRE, fire_layer, function=FunctionId.FIRE)
"""The fire layer; its function falls back on a fault and is never paused."""
