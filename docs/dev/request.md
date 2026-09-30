# External requests

An automation can ask the integration for a position: an alarm clock that opens a bedroom, a scene, the reference run of an actuator that counts its position. This page describes layer 4 of the arbiter, the external request, as block C07 built it for block H07, which offers the actions. The rules come from section 12a and decision 2 of the [domain design specification](../architecture.md); the arbiter that evaluates the layer is described in [The arbiter](arbiter.md). The layer has nothing to do with the protection events and is kept apart from them (ruling of the project owner of 2026-09-28).

| Where | Content |
|---|---|
| `core/request.py` | the layer (`REQUEST_LAYER`), recording and clearing a request, dropping an expired one, its wake-up |
| `WindowState.external_request` | the request as it is persisted: `ExternalRequest` (position, reason text, expiry, arrival) |
| `Engine.request`, `Engine.clear_request` | the façade block H07 calls |

## Recording and clearing

```python
transition = engine.request(state, Position(100), "alarm clock", expires, now=now)
transition = engine.clear_request(state)
```

- `reason` is the text the caller gave. It is kept for the status of the window and never appears in a decision: the decision carries the reason code `external_request`.
- `expires` is the instant at which the request ends by itself; `None` means that it lasts until it is cleared. A request that has expired at its arrival is refused (`ValueError`), and so is a naive time.
- `now` is the arrival. The core reads no clock, so the caller hands it in; it is the trigger of the wish.
- A new request replaces the one before it. Clearing without a request changes nothing.
- Both return a `Transition` without events. The caller persists the state and recomputes the window.

## What the layer wants

While a request stands, the layer wants its position, class comfort, reason `external_request`, with the arrival as the trigger (`Wish.triggered_at`). Otherwise it has no opinion (`inactive`).

- **Below sleep mode, above privacy and shading** (decision 2). A request in a room with active sleep mode is accepted and moves nothing; once sleep mode ends, it wins if it still stands. An automation that wants to open a bedroom in the morning ends the sleep mode of that room first.
- **Fresh.** Its trigger is its arrival, so the minimum interval of motor protection does not hold it back: a request acts at once, also right after another comfort movement. The trigger stays the same while the request stands.
- **Expiry.** `Engine.wake_ups` names the expiry, `Engine.elapse` drops the expired request, and the window is recomputed; nothing is replayed.
- Every other rule applies as to any comfort wish: the manual override and the person-at-the-window dam, pause, the operating mode, every constraint (lockout, ventilation floor, frost, direction), motor protection, dry-run. Fire and protection events rank above it.
- The **reference run** of block H07 is a request with an end position and its own reason.

The function is `request`; like every function that creates comfort wishes it is paused on a fault. It has no settings.

## Testing

`tests/core/test_request.py` has the unit tests, `tests/core/test_sim_request.py` the scenarios `request-below-sleep` (with the test-only stand-in for sleep mode of block C11), `request-expires`, `request-cleared` and `request-dry-run` ([The time-lapse simulation](simulation.md)).
