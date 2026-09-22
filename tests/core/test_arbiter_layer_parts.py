"""One layer, several functions: a layer is registered in parts, one per function.

Shading and solar heating are one layer of the arbiter and two functions of the
integration. Each part is a registration of its own with one function. A part
whose function is disabled for the window is never called; the fault stays
visible in the decision.
"""

import itertools
from collections.abc import Callable

import pytest

from custom_components.roller_shutter_suite.core.arbiter import (
    Arbiter,
    LayerRegistration,
)
from custom_components.roller_shutter_suite.core.engine import build_arbiter
from custom_components.roller_shutter_suite.core.model import (
    FULLY_OPEN,
    Decision,
    FunctionId,
    Layer,
    LayerReason,
    Position,
    WindowConfig,
    Wish,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import LONG_AGO, STUB_LAYERS, day, snapshot, window

type Part = Callable[[WindowConfig, WorldSnapshot], Wish]

DISABLED = ReasonCode.FUNCTION_DISABLED_BY_FAULT
SHADE = Wish.target(
    Layer.SHADING, ReasonCode.SHADING_GEOMETRIC, Position(40)
).triggered(LONG_AGO)
HEAT = Wish.target(Layer.SHADING, ReasonCode.SOLAR_HEATING, FULLY_OPEN).triggered(
    LONG_AGO
)
NO_SUN = Wish.no_opinion(Layer.SHADING, ReasonCode.OUTSIDE_EPISODE)
NOT_COLD = Wish.no_opinion(Layer.SHADING, ReasonCode.INACTIVE)


def _answers(wish: Wish) -> Part:
    return lambda _config, _world: wish


def _never_called(_config: WindowConfig, _world: WorldSnapshot) -> Wish:
    raise AssertionError("the part of a disabled function was evaluated")


def _arbiter(shading: Part, heating: Part) -> Arbiter:
    """Return the stub arbiter with a shading layer of two parts."""
    parts = [
        LayerRegistration(Layer.SHADING, shading, FunctionId.SHADING),
        LayerRegistration(Layer.SHADING, heating, FunctionId.SOLAR_HEATING),
    ]
    others = [entry for entry in STUB_LAYERS if entry.layer is not Layer.SHADING]
    return build_arbiter([*others, *parts])


def _decide(arbiter: Arbiter, *disabled: FunctionId) -> Decision:
    config = window(disabled_functions=set(disabled))
    return arbiter.recompute(config, snapshot(sources=day(), position=70))


def _shading_entries(decision: Decision) -> list[LayerReason]:
    """Return what the parts of the shading layer that did not win say."""
    return [entry for entry in decision.other_layers if entry.layer is Layer.SHADING]


def _shading(reason: ReasonCode) -> LayerReason:
    return LayerReason(Layer.SHADING, reason, FunctionId.SHADING)


def _heating(reason: ReasonCode) -> LayerReason:
    return LayerReason(Layer.SHADING, reason, FunctionId.SOLAR_HEATING)


# --- None disabled -------------------------------------------------------------------


def test_with_nothing_disabled_the_first_part_with_an_opinion_is_the_layers_wish() -> (
    None
):
    """Shading has none, solar heating has one: the layer wants to open."""
    decision = _decide(_arbiter(_answers(NO_SUN), _answers(HEAT)))

    assert decision.winning_wish == HEAT
    assert decision.winning_function is FunctionId.SOLAR_HEATING
    assert _shading_entries(decision) == [_shading(ReasonCode.OUTSIDE_EPISODE)]


def test_when_both_parts_have_an_opinion_the_order_decides_and_the_record_shows_both() -> (
    None
):
    """Shading stands before solar heating; the part that lost says what it wanted."""
    decision = _decide(_arbiter(_answers(SHADE), _answers(HEAT)))

    assert decision.winning_wish == SHADE
    assert decision.winning_function is FunctionId.SHADING
    assert decision.target == Position(40)
    assert _shading_entries(decision) == [_heating(ReasonCode.SOLAR_HEATING)]


def test_without_an_opinion_every_part_gives_its_own_reason() -> None:
    """The schedule below decides; each part says why it stepped aside."""
    decision = _decide(_arbiter(_answers(NO_SUN), _answers(NOT_COLD)))

    assert decision.winning_wish is not None
    assert decision.winning_wish.layer is Layer.SCHEDULE
    assert decision.winning_function is FunctionId.SCHEDULE
    assert _shading_entries(decision) == [
        _shading(ReasonCode.OUTSIDE_EPISODE),
        _heating(ReasonCode.INACTIVE),
    ]


# --- One disabled --------------------------------------------------------------------


def test_with_one_function_disabled_only_the_enabled_part_is_called() -> None:
    """Its wish wins, and the record still names the function that was skipped."""
    decision = _decide(_arbiter(_never_called, _answers(HEAT)), FunctionId.SHADING)

    assert decision.winning_wish == HEAT
    assert decision.winning_function is FunctionId.SOLAR_HEATING
    assert decision.target == FULLY_OPEN
    assert _shading_entries(decision) == [_shading(DISABLED)]


def test_the_wish_of_a_disabled_function_never_comes_about() -> None:
    """Shading would want 40, but it is disabled: the schedule decides."""
    decision = _decide(_arbiter(_never_called, _answers(NOT_COLD)), FunctionId.SHADING)

    assert decision.winning_wish is not None
    assert decision.winning_wish.layer is Layer.SCHEDULE
    assert _shading_entries(decision) == [
        _shading(DISABLED),
        _heating(ReasonCode.INACTIVE),
    ]


def test_the_other_part_can_be_the_disabled_one() -> None:
    """Shading acts; solar heating is never called."""
    decision = _decide(
        _arbiter(_answers(SHADE), _never_called), FunctionId.SOLAR_HEATING
    )
    idle = _decide(_arbiter(_answers(NO_SUN), _never_called), FunctionId.SOLAR_HEATING)

    assert decision.winning_wish == SHADE
    assert decision.winning_function is FunctionId.SHADING
    assert _shading_entries(decision) == [_heating(DISABLED)]
    assert _shading_entries(idle) == [
        _shading(ReasonCode.OUTSIDE_EPISODE),
        _heating(DISABLED),
    ]


# --- Both disabled -------------------------------------------------------------------


def test_with_both_functions_disabled_neither_part_is_called() -> None:
    """Each part says so with its function; the schedule decides."""
    decision = _decide(
        _arbiter(_never_called, _never_called),
        FunctionId.SHADING,
        FunctionId.SOLAR_HEATING,
    )

    assert decision.winning_wish is not None
    assert decision.winning_wish.layer is Layer.SCHEDULE
    assert _shading_entries(decision) == [_shading(DISABLED), _heating(DISABLED)]


def test_the_stub_that_proves_never_called_does_raise_when_it_is_called() -> None:
    """Otherwise the tests above would prove nothing.

    The exception does not leave the recompute; the decision carries it, and
    the part reads ``layer_failed`` instead of ``function_disabled_by_fault``.
    """
    decision = _decide(_arbiter(_never_called, _answers(HEAT)))

    (fault,) = decision.faults
    assert fault.error == "AssertionError"
    assert "was evaluated" in str(fault.exception)
    assert _shading_entries(decision) == [_shading(ReasonCode.LAYER_FAILED)]


# --- Order ---------------------------------------------------------------------------


def test_parts_are_asked_in_the_order_of_the_functions_not_of_registration() -> None:
    """Both parts have an opinion: shading stands before solar heating."""
    parts = [
        LayerRegistration(Layer.SHADING, _answers(SHADE), FunctionId.SHADING),
        LayerRegistration(Layer.SHADING, _answers(HEAT), FunctionId.SOLAR_HEATING),
    ]
    others = [entry for entry in STUB_LAYERS if entry.layer is not Layer.SHADING]
    forward = build_arbiter([*others, *parts])
    backward = build_arbiter([*parts[::-1], *others[::-1]])

    assert [
        entry.function for entry in backward.layers if entry.layer is Layer.SHADING
    ] == [FunctionId.SHADING, FunctionId.SOLAR_HEATING]
    assert backward.layers == forward.layers
    disabled_sets: list[tuple[FunctionId, ...]] = [
        (),
        (FunctionId.SHADING,),
        (FunctionId.SOLAR_HEATING,),
        (FunctionId.SHADING, FunctionId.SOLAR_HEATING),
    ]
    for disabled in disabled_sets:
        assert _decide(forward, *disabled) == _decide(backward, *disabled), disabled
    assert _decide(forward).winning_wish == SHADE


def test_every_order_of_registration_gives_the_same_arbiter() -> None:
    """Three parts and the other layers, in every permutation of the parts."""
    parts = [
        LayerRegistration(Layer.SHADING, _answers(SHADE), FunctionId.SHADING),
        LayerRegistration(Layer.SHADING, _answers(HEAT), FunctionId.SOLAR_HEATING),
        LayerRegistration(Layer.SCHEDULE, _answers(NO_SUN), FunctionId.SCHEDULE),
    ]
    expected = build_arbiter(parts).layers

    for order in itertools.permutations(parts):
        assert build_arbiter(order).layers == expected


# --- Registry ------------------------------------------------------------------------


def test_the_parts_of_a_layer_have_different_functions() -> None:
    """The same function twice is refused with a message that says so."""
    part = LayerRegistration(Layer.SHADING, _answers(SHADE), FunctionId.SHADING)
    again = LayerRegistration(Layer.SHADING, _answers(HEAT), FunctionId.SHADING)

    with pytest.raises(
        ValueError, match=r"'shading' is registered twice for the function 'shading'"
    ):
        build_arbiter([part, again])


def test_only_a_comfort_layer_has_parts() -> None:
    """Fire and protection are one registration each, whatever they declare."""

    def alarm(_config: WindowConfig, _world: WorldSnapshot) -> Wish:
        return Wish.target(Layer.FIRE, ReasonCode.FIRE_ALARM, FULLY_OPEN)

    declared = LayerRegistration(Layer.FIRE, alarm, FunctionId.FIRE)
    undeclared = LayerRegistration(Layer.FIRE, alarm)

    with pytest.raises(ValueError, match="'fire' is registered twice"):
        build_arbiter([declared, undeclared])
    with pytest.raises(ValueError, match="'fire' is registered twice"):
        build_arbiter([undeclared, undeclared])


def test_every_part_is_a_comfort_part_with_a_function_that_can_be_paused() -> None:
    """The rule per registration holds for each part."""
    with pytest.raises(ValueError, match="one that is paused on a fault"):
        LayerRegistration(Layer.SHADING, _answers(HEAT), FunctionId.VENTILATION)
    with pytest.raises(ValueError, match="one that is paused on a fault"):
        LayerRegistration(Layer.SHADING, _answers(HEAT))
