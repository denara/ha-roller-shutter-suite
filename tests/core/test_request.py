"""The external request layer (layer 4 of section 2.1; section 12a).

Kept apart from the protection events of block C07 (ruling of the project
owner of 2026-09-28): its own module (``core/request.py``), its own tests,
its own section of the specification and its own scenarios
(``test_sim_request.py``).
"""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from custom_components.roller_shutter_suite.core.engine import Engine, build_arbiter
from custom_components.roller_shutter_suite.core.model import (
    AnySourceValue,
    Decision,
    ExternalRequest,
    FunctionId,
    GateKind,
    Layer,
    PersonAtWindowDam,
    Position,
    SourceValue,
    WindowState,
    WishClass,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from custom_components.roller_shutter_suite.core.request import (
    REQUEST_LAYER,
    clear_request,
    request,
    request_after,
    request_layer,
    standing_request,
)
from tests.core.arbiter_kit import NOW, STUB_LAYERS, day, window
from tests.core.protection_kit import override, world
from tests.sim.stand_ins import SLEEP_SOURCE, SLEEP_STAND_IN

MINUTE = timedelta(minutes=1)
LATER = NOW + timedelta(hours=1)


def _requested(
    position: int = 40, expires: datetime | None = LATER, at: datetime = NOW
) -> WindowState:
    return Engine.request(
        WindowState(), Position(position), "scene", expires, now=at
    ).state


def engine(*, stand_ins: bool = False) -> Engine:
    """Return an engine with the request layer, the stub layers and the real rules.

    ``stand_ins`` puts the stand-in for sleep mode of block C11 in place of
    the sleep stub.
    """
    layers = [
        entry for entry in STUB_LAYERS if not (stand_ins and entry.layer is Layer.SLEEP)
    ]
    if stand_ins:
        layers.append(SLEEP_STAND_IN)
    return Engine(window(), build_arbiter([*layers, REQUEST_LAYER]))


def _decide(
    machine: Engine,
    state: WindowState,
    *,
    at: datetime = NOW,
    sources: dict[str, AnySourceValue] | None = None,
) -> Decision:
    snapshot = world(day(**(sources or {})), state=state, at=at)
    transition = machine.elapse(snapshot, None)
    return machine.recompute(replace(snapshot, state=transition.state))


def test_a_request_is_recorded_with_its_arrival_and_replaces_an_older_one() -> None:
    """The arrival is the trigger of its wish; the text is kept for the status."""
    first = _requested(40)
    second = request(first, Position(70), "reference run", None, now=NOW + MINUTE).state

    assert first.external_request == ExternalRequest(
        Position(40), "scene", expires_at=LATER, requested_at=NOW
    )
    assert second.external_request == ExternalRequest(
        Position(70), "reference run", requested_at=NOW + MINUTE
    )
    assert Engine.request(WindowState(), Position(40), "x", None, now=NOW).events == ()


def test_a_request_expires_after_it_arrives() -> None:
    """The model refuses one that has expired at its arrival; a naive time too."""
    with pytest.raises(ValueError, match="expires after it arrives"):
        request(WindowState(), Position(40), "scene", NOW, now=NOW)
    with pytest.raises(ValueError, match="timezone-aware"):
        request(
            WindowState(), Position(40), "scene", None, now=NOW.replace(tzinfo=None)
        )


def test_the_request_wins_as_a_fresh_comfort_wish_until_it_expires() -> None:
    """Class comfort, ``external_request``, the arrival as the trigger."""
    state = _requested()

    wish = request_layer(window(), world(day(), state=state))

    assert wish.layer is Layer.EXTERNAL_REQUEST
    assert wish.reason is ReasonCode.EXTERNAL_REQUEST
    assert wish.wish_class is WishClass.COMFORT
    assert wish.position == Position(40)
    assert wish.triggered_at == NOW
    expired = request_layer(window(), world(day(), state=state, at=LATER))
    assert expired.reason is ReasonCode.INACTIVE
    assert standing_request(state, LATER) is None
    assert request_layer(window(), world(day())).reason is ReasonCode.INACTIVE


def test_a_request_is_not_held_back_by_the_minimum_interval() -> None:
    """A fresh wish: its trigger lies after the last own comfort movement."""
    moved = replace(_requested(at=NOW), last_comfort_movement=NOW - 2 * MINUTE)

    decision = _decide(engine(), moved)

    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.EXTERNAL_REQUEST
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND


def test_a_request_below_an_active_sleep_mode_waits_and_moves_nothing() -> None:
    """Decision 2: accepted, but the sleep layer wins above it."""
    machine = engine(stand_ins=True)

    decision = _decide(
        machine, _requested(100), sources={SLEEP_SOURCE: SourceValue.of(True)}
    )

    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.SLEEP_MODE
    (asked,) = (e for e in decision.other_layers if e.layer is Layer.EXTERNAL_REQUEST)
    assert asked.reason is ReasonCode.EXTERNAL_REQUEST
    assert asked.function is FunctionId.REQUEST


def test_a_protection_event_and_fire_rank_above_a_request() -> None:
    """The storm and the fire alarm win although an automation asked for 40."""
    machine = engine()

    stormy = _decide(machine, _requested(), sources={"storm": SourceValue.of(True)})
    burning = _decide(
        machine, _requested(), sources={"fire_alarm": SourceValue.of(True)}
    )

    assert stormy.winning_wish is not None
    assert stormy.winning_wish.reason is ReasonCode.PROTECTION_EVENT
    assert burning.winning_wish is not None
    assert burning.winning_wish.reason is ReasonCode.FIRE_ALARM


@pytest.mark.parametrize("person", [False, True], ids=["manual override", "person"])
def test_both_dams_hold_a_request_back(*, person: bool) -> None:
    """Section 12a: every rule of a comfort wish applies, the two dams included.

    A person moved the window by hand, so the request of an automation wins
    the decision and is held back; it moves nothing until the dam ends.
    """
    requested = _requested(70)
    state = (
        replace(requested, person_at_window=PersonAtWindowDam(ends_at=LATER))
        if person
        else replace(requested, manual_override=override())
    )

    decision = _decide(engine(), state)

    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.EXTERNAL_REQUEST
    assert decision.gate is not None
    held_by = ReasonCode.PERSON_AT_WINDOW if person else ReasonCode.MANUAL_OVERRIDE
    assert decision.gate.reason is held_by
    assert decision.gate.kind is not GateKind.SEND


def test_clearing_removes_the_request_and_the_schedule_acts_again() -> None:
    """Without a request nothing changes."""
    cleared = Engine.clear_request(_requested())
    nothing = clear_request(cleared.state)

    assert cleared.state.external_request is None
    assert nothing.state is cleared.state
    decision = _decide(engine(), cleared.state)
    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.SCHEDULE_DAY


def test_elapse_drops_an_expired_request_and_wakes_the_window_at_its_expiry() -> None:
    """The caller wakes the window at the expiry and recomputes."""
    state = _requested()
    machine = engine()

    assert LATER in machine.wake_ups(state, NOW, dry_run=False)
    assert request_after(world(day(), state=state)).state is state
    dropped = machine.elapse(world(day(), state=state, at=LATER), None)
    assert dropped.state.external_request is None
    assert dropped.events == ()
    endless = _requested(expires=None)
    assert machine.wake_ups(endless, NOW, dry_run=False) == ()
    assert request_after(world(day())).state == WindowState()


def test_a_request_written_without_its_arrival_is_never_fresh() -> None:
    """Data of an older version: the wish states no trigger."""
    state = WindowState(external_request=ExternalRequest(Position(40), "scene"))

    wish = request_layer(window(), world(day(), state=state))

    assert wish.triggered_at is None
    assert wish.position == Position(40)


def test_the_arrival_goes_through_plain_data_and_is_optional() -> None:
    """Optional within schema version 1."""
    state = _requested()
    data = state.external_request.to_data()  # type: ignore[union-attr]

    assert ExternalRequest.from_data(data) == state.external_request
    del data["requested_at"]
    assert ExternalRequest.from_data(data).requested_at is None


def test_the_layer_is_registered_for_its_function() -> None:
    """``request`` is paused on a fault, like every comfort function."""
    assert REQUEST_LAYER.layer is Layer.EXTERNAL_REQUEST
    assert REQUEST_LAYER.function is FunctionId.REQUEST
    assert REQUEST_LAYER.can_be_paused
