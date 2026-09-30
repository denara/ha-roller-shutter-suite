"""Layer 4: the external request (F1, A11; section 12a of the specification).

An automation requests a position, with a reason text and an expiry
(``Engine.request``), and clears it (``Engine.clear_request``). The request is
persisted as ``WindowState.external_request``. Until it expires or is cleared
the layer wants the requested position as a wish of class comfort with the
reason ``external_request``. The text the caller gave is a subject for the
status and never part of a decision.

- **Its place** (decision 2): below sleep mode, above privacy and shading. A
  request in a room with active sleep mode is accepted, waits below the sleep
  layer, and moves nothing; an automation that wants to open such a room (an
  alarm clock) ends the sleep mode of that room first.
- **Its trigger** is its arrival (``ExternalRequest.requested_at``): a request
  is a fresh wish, and the minimum interval of motor protection does not hold
  it back. It stays the same while the request stands, so a request that wins
  again after a higher layer dropped out is not fresh any more.
- **Its expiry** is an instant: the layer has no opinion from then on, the
  caller wakes the window at it (``Engine.wake_ups``), and ``Engine.elapse``
  drops the expired request.
- Every other rule applies as to any comfort wish: the dams, pause, the
  operating mode, every constraint, motor protection, dry-run. The reference
  run of block H07 is a request with an end position and its own reason.

The function is ``request``; it is paused on a fault like every function that
creates comfort wishes. It has no settings.
"""

from dataclasses import replace
from datetime import datetime
from typing import Final

from .arbiter import LayerRegistration
from .model import (
    ExternalRequest,
    FunctionId,
    Layer,
    Position,
    Transition,
    WindowConfig,
    WindowState,
    Wish,
    WorldSnapshot,
)
from .model._validation import require_aware
from .reasons import ReasonCode


def standing_request(state: WindowState, now: datetime) -> ExternalRequest | None:
    """Return the request that stands at this moment; ``None``: none, or expired."""
    request = state.external_request
    if request is None:
        return None
    if request.expires_at is not None and request.expires_at <= now:
        return None
    return request


def request_layer(_config: WindowConfig, snapshot: WorldSnapshot) -> Wish:
    """Return the requested position until the request expires or is cleared."""
    request = standing_request(snapshot.state, snapshot.time)
    if request is None:
        return Wish.no_opinion(Layer.EXTERNAL_REQUEST, ReasonCode.INACTIVE)
    wish = Wish.target(
        Layer.EXTERNAL_REQUEST, ReasonCode.EXTERNAL_REQUEST, request.position
    )
    if request.requested_at is None:
        # Written before the arrival was kept: the wish is never fresh.
        return wish
    return wish.triggered(request.requested_at)


def request(
    state: WindowState,
    position: Position,
    reason: str,
    expires: datetime | None,
    *,
    now: datetime,
) -> Transition:
    """Return the state with a new request, which replaces an older one.

    ``expires`` is when the request ends by itself (``None``: when it is
    cleared); it lies after ``now``, the arrival, which is the trigger of
    its wish. The model refuses a request that has expired at its arrival.
    """
    require_aware(now, "the arrival of a request")
    return Transition(
        replace(
            state,
            external_request=ExternalRequest(
                position=position,
                reason=reason,
                expires_at=expires,
                requested_at=now,
            ),
        )
    )


def clear_request(state: WindowState) -> Transition:
    """Return the state without the request; without one nothing changes."""
    if state.external_request is None:
        return Transition(state)
    return Transition(replace(state, external_request=None))


def request_after(snapshot: WorldSnapshot) -> Transition:
    """Return the state with an expired request dropped; the part of ``elapse``."""
    state = snapshot.state
    if state.external_request is None or standing_request(state, snapshot.time):
        return Transition(state)
    return Transition(replace(state, external_request=None))


def request_wake_ups(state: WindowState) -> set[datetime]:
    """Return the expiry of the request, if it has one."""
    request_ = state.external_request
    if request_ is None or request_.expires_at is None:
        return set()
    return {request_.expires_at}


REQUEST_LAYER: Final = LayerRegistration(
    Layer.EXTERNAL_REQUEST, request_layer, function=FunctionId.REQUEST
)
"""The external request layer; its function is paused on a fault."""
