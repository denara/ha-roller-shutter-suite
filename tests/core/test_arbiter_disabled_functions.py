"""Comfort becomes cautious: a function disabled by a data fault gives no wish.

A window can have comfort functions disabled because a stored setting in their
inheritance chain is faulty. A window must never move unexpectedly because of
a data fault, so the arbiter does not ask the layer of such a function; the
decision says why. Fire and protection are never disabled.
"""

from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.arbiter import (
    LayerRegistration,
    disabled_functions,
)
from custom_components.roller_shutter_suite.core.engine import build_arbiter
from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    GateOutcome,
    Layer,
    LayerReason,
    MemberTarget,
    Position,
    SourceValue,
    WindowConfig,
    Wish,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import (
    ReasonCategory,
    ReasonCode,
)
from tests.core.arbiter_kit import (
    ARMED,
    DRY_RUN,
    FUNCTION_OF,
    LEFT,
    day,
    engine,
    fire,
    night,
    schedule_layer,
    snapshot,
    storm,
    window,
)

DISABLED = ReasonCode.FUNCTION_DISABLED_BY_FAULT
SHADED = day(shading_position=SourceValue.of(40))


def test_a_disabled_comfort_function_yields_no_wish_and_says_why() -> None:
    """Shading is disabled: the schedule below it decides, and the record shows it."""
    config = window(disabled_functions={"shading"})

    decision = engine(config).recompute(snapshot(sources=SHADED, position=0))

    assert decision.winning_wish is not None
    assert decision.winning_wish.layer is Layer.SCHEDULE
    assert decision.target == FULLY_OPEN
    assert LayerReason(Layer.SHADING, DISABLED) in decision.other_layers
    assert DISABLED.category is ReasonCategory.LAYER_INACTIVE


def test_the_layer_of_a_disabled_function_is_not_even_asked() -> None:
    """Its settings are faulty; evaluating it could fail or mislead."""

    def explodes(_config: WindowConfig, _world: WorldSnapshot) -> Wish:
        raise AssertionError("the layer of a disabled function was evaluated")

    arbiter = build_arbiter([LayerRegistration(Layer.SCHEDULE, explodes, "schedule")])

    decision = arbiter.recompute(
        window(disabled_functions={"schedule"}), snapshot(sources=night())
    )

    assert decision.winning_wish is None
    assert decision.gate is None
    assert LayerReason(Layer.SCHEDULE, DISABLED) in decision.other_layers
    with pytest.raises(AssertionError, match="was evaluated"):
        arbiter.recompute(window(), snapshot(sources=night()))


def test_with_every_comfort_function_disabled_nothing_moves_and_dry_run_shows_why() -> (
    None
):
    """No winner, no target, no gate outcome; each comfort layer names the fault."""
    config = window(disabled_functions=set(FUNCTION_OF.values()))
    sources = night(sleep=SourceValue.of(True), shading_position=SourceValue.of(40))

    for controls in (ARMED, DRY_RUN):
        decision = engine(config).recompute(
            snapshot(sources=sources, controls=controls)
        )

        assert decision.winning_wish is None
        assert decision.targets == ()
        assert decision.gate is None
        disabled = {
            entry.layer for entry in decision.other_layers if entry.reason is DISABLED
        }
        assert disabled == {Layer.SLEEP, Layer.SHADING, Layer.SCHEDULE}


def test_lower_comfort_layers_still_act() -> None:
    """Sleep mode is disabled; shading below it wins as if sleep were not there."""
    config = window(disabled_functions={"sleep"})
    sources = day(sleep=SourceValue.of(True), shading_position=SourceValue.of(40))

    decision = engine(config).recompute(snapshot(sources=sources, position=100))

    assert decision.winning_wish is not None
    assert decision.winning_wish.layer is Layer.SHADING
    assert decision.target == Position(40)
    assert decision.gate == GateOutcome.send()


@pytest.mark.parametrize(
    ("sources", "layer", "target"),
    [(fire(), Layer.FIRE, FULLY_OPEN), (storm(), Layer.PROTECTION, FULLY_CLOSED)],
)
def test_fire_and_protection_are_never_disabled(
    sources: dict[str, Any], layer: Layer, target: Position
) -> None:
    """Also when somebody puts their names into the set, and with all comfort off."""
    everything = {"fire", "protection", *FUNCTION_OF.values()}
    config = window(disabled_functions=everything)

    decision = engine(config).recompute(snapshot(sources=sources))

    assert decision.winning_wish is not None
    assert decision.winning_wish.layer is layer
    assert decision.targets == (MemberTarget(LEFT, target),)
    assert decision.gate == GateOutcome.send()


def test_a_function_that_fire_or_protection_declares_is_ignored() -> None:
    """Even a registration that names a disabled function keeps answering."""

    def alarm(_config: WindowConfig, _world: WorldSnapshot) -> Wish:
        return Wish.target(Layer.FIRE, ReasonCode.FIRE_ALARM, FULLY_OPEN)

    def hail(_config: WindowConfig, _world: WorldSnapshot) -> Wish:
        return Wish.target(Layer.PROTECTION, ReasonCode.PROTECTION_EVENT, FULLY_OPEN)

    config = window(disabled_functions={"fire", "protection"})

    for layer, evaluate, function in (
        (Layer.FIRE, alarm, "fire"),
        (Layer.PROTECTION, hail, "protection"),
    ):
        registration = LayerRegistration(layer, evaluate, function)
        decision = build_arbiter([registration]).recompute(config, snapshot())

        assert registration.can_be_disabled is False
        assert decision.winning_wish is not None
        assert decision.winning_wish.layer is layer


def test_the_return_to_the_manual_position_is_not_disabled_either() -> None:
    """It is a comfort wish, but it comes from the protection layer."""
    config = window(disabled_functions=set(FUNCTION_OF.values()))

    decision = engine(config).recompute(
        snapshot(sources=day(return_to=SourceValue.of(40)), position=0)
    )

    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.PROTECTION_RETURN_MANUAL
    assert decision.target == Position(40)


def test_the_registry_refuses_a_comfort_layer_without_a_function() -> None:
    """Every comfort layer declares the function it belongs to."""
    bad: Any = 7
    for layer in (Layer.SLEEP, Layer.EXTERNAL_REQUEST, Layer.PRIVACY, Layer.SHADING):
        with pytest.raises(ValueError, match=f"comfort layer '{layer.value}' declares"):
            LayerRegistration(layer, schedule_layer)
    with pytest.raises(ValueError, match="comfort layer 'schedule' declares"):
        LayerRegistration(Layer.SCHEDULE, schedule_layer)
    with pytest.raises(ValueError, match="non-empty identifier"):
        LayerRegistration(Layer.SCHEDULE, schedule_layer, "")
    with pytest.raises(ValueError, match="non-empty identifier"):
        LayerRegistration(Layer.SCHEDULE, schedule_layer, bad)
    assert LayerRegistration(Layer.FIRE, schedule_layer).function is None
    assert LayerRegistration(Layer.PROTECTION, schedule_layer).function is None


def test_the_disabled_functions_of_a_window_are_a_frozen_set_of_identifiers() -> None:
    """Empty by default; the arbiter reads them in one place."""
    bad: Any = 7

    assert window().disabled_functions == frozenset()
    assert disabled_functions(window()) == frozenset()
    config = window(disabled_functions=["shading", "shading", "privacy"])
    assert disabled_functions(config) == frozenset({"shading", "privacy"})
    assert isinstance(config.disabled_functions, frozenset)
    assert hash(config) == hash(window(disabled_functions={"privacy", "shading"}))
    with pytest.raises(ValueError, match="must not be empty"):
        window(disabled_functions={""})
    with pytest.raises(TypeError, match="disabled function"):
        window(disabled_functions={bad})
