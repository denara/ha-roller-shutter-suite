"""What the members of a window report: from cover states to observations.

The core sees a member through an :class:`Observation`: a state class
(resting, moving up, moving down, unavailable) and a position, if the member
reports one. This module reads both from the state of a cover entity:

- no state, or the state ``unavailable``: the member is **unavailable**;
- ``opening`` and ``closing``: the member is **moving**; anything else,
  including ``unknown`` (a cover without feedback often stays there), is
  **resting**;
- the position is ``current_position`` if the capability profile says that
  the member reports one and the attribute holds a whole number from 0 to
  100; otherwise the member reports none. A value outside that range is not
  a position and is never rounded into one.

This is the input side only. Reducing reports to observations that carry new
information (dropping duplicate writes), the tracker per member and manual
detection belong to the block that builds the tracking.
"""

from homeassistant.components.cover import ATTR_CURRENT_POSITION, CoverState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State

from .core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
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


def observe_member(hass: HomeAssistant, member: MemberConfig) -> MemberObservation:
    """Return the observation of one member from the state of its cover."""
    state = hass.states.get(member.member_id)
    if state is None or state.state == STATE_UNAVAILABLE:
        return MemberObservation(member.member_id, UNAVAILABLE_MEMBER)
    if state.state == CoverState.OPENING:
        movement = MovementState.MOVING_UP
    elif state.state == CoverState.CLOSING:
        movement = MovementState.MOVING_DOWN
    else:
        movement = MovementState.RESTING
    position = _position_of(state) if member.capabilities.reports_position else None
    return MemberObservation(member.member_id, Observation(movement, position))


def observe_window(hass: HomeAssistant, config: WindowConfig) -> WindowObservation:
    """Return the observed window: every member, in the order of the configuration."""
    return WindowObservation(
        tuple(observe_member(hass, member) for member in config.members)
    )
