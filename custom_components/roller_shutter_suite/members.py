"""What the members of a window report: from cover states to observations.

The core sees a member through an :class:`Observation`: a state class
(resting, moving up, moving down, unavailable) and a position, if the member
reports one. This module reads both from the state of a cover entity:

- no state, or the state ``unavailable``: the member is **unavailable**;
- ``opening`` and ``closing``: the member is **moving**; anything else,
  including ``unknown`` (a cover without feedback often stays there), is
  **resting**;
- the position is ``current_position`` if the attribute holds a whole number
  from 0 to 100 and the capability profile does not say that the member
  definitely reports none (``capability_state("reports_position")`` is
  ``MISSING``). A profile whose capabilities are not known yet keeps the
  position: unknown is never taken for missing. A value outside that range,
  a boolean, text or a float (some platforms write ``50.0``) is not a
  position and is never rounded into one.

This is the input side only. The controller hands every observation to the
movement tracker of the core (``Engine.observe``), which drops one that
carries no new information (a duplicate write) and tells an own movement
from somebody else's.
"""

from homeassistant.components.cover import ATTR_CURRENT_POSITION, CoverState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State

from .core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    CapabilityState,
    MemberConfig,
    MemberObservation,
    MovementState,
    Observation,
    Position,
    WindowConfig,
    WindowObservation,
)

UNAVAILABLE_MEMBER = Observation(MovementState.UNAVAILABLE)


def _position_of(state: State) -> Position | None:
    raw = state.attributes.get(ATTR_CURRENT_POSITION)
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    if not FULLY_CLOSED.value <= raw <= FULLY_OPEN.value:
        return None
    return Position(raw)


def observation_of(state: State | None, member: MemberConfig) -> Observation:
    """Return the observation of one member from a state of its cover.

    ``state`` is the state as Home Assistant has it now, or the new state a
    state change carries; ``None`` is a cover without a state.
    """
    if state is None or state.state == STATE_UNAVAILABLE:
        return UNAVAILABLE_MEMBER
    if state.state == CoverState.OPENING:
        movement = MovementState.MOVING_UP
    elif state.state == CoverState.CLOSING:
        movement = MovementState.MOVING_DOWN
    else:
        movement = MovementState.RESTING
    feedback = member.capabilities.capability_state("reports_position")
    position = None if feedback is CapabilityState.MISSING else _position_of(state)
    return Observation(movement, position)


def observe_member(hass: HomeAssistant, member: MemberConfig) -> MemberObservation:
    """Return the observation of one member from the state of its cover."""
    return MemberObservation(
        member.member_id, observation_of(hass.states.get(member.member_id), member)
    )


def observe_window(hass: HomeAssistant, config: WindowConfig) -> WindowObservation:
    """Return the observed window: every member, in the order of the configuration."""
    return WindowObservation(
        tuple(observe_member(hass, member) for member in config.members)
    )
