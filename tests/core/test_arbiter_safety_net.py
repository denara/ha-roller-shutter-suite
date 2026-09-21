"""The safety net of the arbiter: an exception never loosens and never stops protection.

A programming error must not be able to do what a data fault may not. No
exception that a layer, a part of a layer, a constraint or a gate rule raises
leaves ``recompute``:

- a layer or a part that raises has no opinion (``layer_failed``);
- a constraint that raises applies its cautious result (``constraint_failed``);
- a gate rule that raises holds the wish back (``gate_rule_failed``), with one
  exception that the project owner decided: a failed dry-run rule sends a
  pending fire wish.

The fire layer and the protection layer are always asked, and a fire wish is
never asked the rules of the fire bypass. Every case is a fact in
``Decision.faults`` as well.

The stubs here raise for every kind of registration. They stay although the
first known case, the frost reader, no longer raises.
"""

from dataclasses import replace
from typing import NoReturn

import pytest

from custom_components.roller_shutter_suite.core.arbiter import (
    BUILT_IN_GATE_RULES,
    Arbiter,
    ConstraintInput,
    ConstraintRegistration,
    GateRuleRegistration,
    LayerRegistration,
)
from custom_components.roller_shutter_suite.core.constraints import (
    DIRECTION_CONSTRAINT,
    FROST_CONSTRAINT,
)
from custom_components.roller_shutter_suite.core.engine import (
    BUILT_IN_CONSTRAINTS,
    Engine,
    build_arbiter,
)
from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    AnySourceValue,
    Constraint,
    ConstraintResult,
    Controls,
    Decision,
    EvaluationFault,
    EvaluationStage,
    FrostSettings,
    FunctionId,
    GateKind,
    GateRule,
    Layer,
    LayerReason,
    MemberTarget,
    Position,
    SourceValue,
    WindowConfig,
    Wish,
    WishClass,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import (
    ARMED,
    DRY_RUN,
    FUNCTION_OF,
    LEFT,
    NOW,
    STUB_LAYERS,
    day,
    fire,
    on_level,
    registered,
    snapshot,
    storm,
    window,
)


class BrokenError(Exception):
    """What the stubs raise: an exception no code of the core knows."""


def _raises(*_arguments: object) -> NoReturn:
    raise BrokenError("a programming error in a registered function")


def _layers(*broken: Layer) -> tuple[LayerRegistration, ...]:
    """Return the stub layers, with the given ones replaced by layers that raise."""
    return tuple(
        registered(entry.layer, _raises) if entry.layer in broken else entry
        for entry in STUB_LAYERS
    )


def _gate_rules(*broken: GateRule) -> tuple[GateRuleRegistration, ...]:
    """Return the built-in gate rules, with every part of the given ones raising."""
    return tuple(
        replace(entry, evaluate=_raises) if entry.rule in broken else entry
        for entry in BUILT_IN_GATE_RULES
    )


def _arbiter(
    *,
    layers: tuple[LayerRegistration, ...] = STUB_LAYERS,
    constraints: tuple[ConstraintRegistration, ...] = BUILT_IN_CONSTRAINTS,
    gate_rules: tuple[GateRuleRegistration, ...] = BUILT_IN_GATE_RULES,
) -> Arbiter:
    return Arbiter(layers=layers, constraints=constraints, gate_rules=gate_rules)


def _decide(
    arbiter: Arbiter,
    sources: dict[str, AnySourceValue],
    *,
    config: WindowConfig | None = None,
    position: int = 50,
    controls: Controls = ARMED,
) -> Decision:
    return arbiter.recompute(
        window() if config is None else config,
        snapshot(sources=sources, position=position, controls=controls),
    )


def _fault(
    place: Layer | Constraint | GateRule, function: FunctionId | None
) -> EvaluationFault:
    """Return the fault the stubs cause at a place; the exception is not compared."""
    return EvaluationFault.of(place, function, BrokenError())


WORLDS = {
    WishClass.FIRE: fire,
    WishClass.PROTECTION: storm,
    WishClass.COMFORT: day,
}
"""A world in which a wish of each class wins: fire opens, the storm closes."""

TARGETS = {
    WishClass.FIRE: FULLY_OPEN,
    WishClass.PROTECTION: FULLY_CLOSED,
    WishClass.COMFORT: FULLY_OPEN,
}
ALL = list(WishClass)


# --- Layers -------------------------------------------------------------------------


def test_comfort_layer_that_raises_has_no_opinion_and_the_next_layer_decides() -> None:
    """Sleep mode is on, but its layer is broken: the schedule decides."""
    sources = day(sleep=SourceValue.of(True))

    decision = _decide(_arbiter(layers=_layers(Layer.SLEEP)), sources)

    assert decision.winning_wish is not None
    assert decision.winning_wish.layer is Layer.SCHEDULE
    assert LayerReason(Layer.SLEEP, ReasonCode.LAYER_FAILED, FunctionId.SLEEP) in (
        decision.other_layers
    )
    assert decision.faults == (_fault(Layer.SLEEP, FunctionId.SLEEP),)
    fault = decision.faults[0]
    assert (fault.stage, fault.error) == (EvaluationStage.LAYER, "BrokenError")
    assert isinstance(fault.exception, BrokenError)
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND


def test_part_of_a_layer_that_raises_leaves_the_other_part_its_say() -> None:
    """Shading is broken; solar heating, the other part of the layer, still answers."""
    heat = Wish.target(Layer.SHADING, ReasonCode.SOLAR_HEATING, FULLY_OPEN).triggered(
        NOW
    )
    parts = (
        LayerRegistration(Layer.SHADING, _raises, FunctionId.SHADING),
        LayerRegistration(
            Layer.SHADING, lambda _config, _world: heat, FunctionId.SOLAR_HEATING
        ),
    )

    decision = _decide(_arbiter(layers=parts), {})

    assert decision.winning_wish == heat
    assert decision.winning_function is FunctionId.SOLAR_HEATING
    assert LayerReason(Layer.SHADING, ReasonCode.LAYER_FAILED, FunctionId.SHADING) in (
        decision.other_layers
    )
    assert decision.faults == (_fault(Layer.SHADING, FunctionId.SHADING),)


@pytest.mark.parametrize("wish_class", [WishClass.FIRE, WishClass.PROTECTION])
def test_fire_and_protection_are_decided_although_every_comfort_layer_raises(
    wish_class: WishClass,
) -> None:
    """Whatever comfort raises, the fire and the protection layer are evaluated."""
    comfort = tuple(layer for layer in Layer if layer.wish_class is WishClass.COMFORT)
    arbiter = _arbiter(layers=_layers(*comfort))

    decision = _decide(arbiter, WORLDS[wish_class]())

    assert decision.winning_wish is not None
    assert decision.winning_wish.wish_class is wish_class
    assert decision.target == TARGETS[wish_class]
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND
    failed = [
        entry.layer
        for entry in decision.other_layers
        if entry.reason is ReasonCode.LAYER_FAILED
    ]
    assert failed == [Layer.SLEEP, Layer.SHADING, Layer.SCHEDULE]
    assert [fault.place for fault in decision.faults] == failed


def test_fire_layer_that_raises_is_reported_and_the_other_layers_still_run() -> None:
    """It cannot be replaced by a cautious value; the decision says that it failed."""
    decision = _decide(_arbiter(layers=_layers(Layer.FIRE)), storm())

    assert decision.winning_wish is not None
    assert decision.winning_wish.layer is Layer.PROTECTION
    assert decision.target == FULLY_CLOSED
    assert decision.other_layers[0] == LayerReason(
        Layer.FIRE, ReasonCode.LAYER_FAILED, FunctionId.FIRE
    )
    assert decision.faults == (_fault(Layer.FIRE, FunctionId.FIRE),)


def test_protection_layer_that_raises_stops_neither_fire_nor_comfort() -> None:
    """Fire above it is decided, and without fire the schedule below it."""
    arbiter = _arbiter(layers=_layers(Layer.PROTECTION))
    failed = LayerReason(
        Layer.PROTECTION, ReasonCode.LAYER_FAILED, FunctionId.PROTECTION_EVENTS
    )

    burning = _decide(arbiter, fire())
    calm = _decide(arbiter, day())

    assert burning.winning_wish is not None
    assert burning.winning_wish.layer is Layer.FIRE
    assert burning.gate is not None
    assert burning.gate.kind is GateKind.SEND
    assert calm.winning_wish is not None
    assert calm.winning_wish.layer is Layer.SCHEDULE
    for decision in (burning, calm):
        assert failed in decision.other_layers
        assert decision.faults == (
            _fault(Layer.PROTECTION, FunctionId.PROTECTION_EVENTS),
        )


def test_every_layer_raises_and_nothing_moves() -> None:
    """No winner, no target, no gate; seven faults, no exception."""
    decision = _decide(_arbiter(layers=_layers(*Layer)), fire())

    assert decision.winning_wish is None
    assert decision.gate is None
    assert {entry.reason for entry in decision.other_layers} >= {
        ReasonCode.LAYER_FAILED
    }
    assert [fault.place for fault in decision.faults] == [
        entry.layer for entry in _arbiter().layers
    ]


def test_layer_cannot_say_by_itself_that_it_failed() -> None:
    """The reason is the arbiter's; a layer that uses it has failed indeed."""
    liar = registered(
        Layer.SLEEP,
        lambda _config, _world: Wish.no_opinion(Layer.SLEEP, ReasonCode.LAYER_FAILED),
    )

    decision = _decide(build_arbiter([liar]), {})

    (fault,) = decision.faults
    assert "only the arbiter says that a layer failed" in str(fault.exception)


def test_answer_that_is_no_wish_counts_as_raised() -> None:
    """A layer that returns nothing at all has no opinion either."""
    silent = registered(Layer.SLEEP, lambda _config, _world: None)  # type: ignore[arg-type,return-value]

    decision = _decide(build_arbiter([silent]), {})

    (fault,) = decision.faults
    assert fault.error == "TypeError"
    assert decision.winning_wish is None


# --- Constraints --------------------------------------------------------------------


def _broken(
    constraint: Constraint = Constraint.VENTILATION_FLOOR,
    function: FunctionId | None = FunctionId.VENTILATION,
    **extra: object,
) -> ConstraintRegistration:
    return ConstraintRegistration(
        constraint=constraint,
        applies_to=frozenset({WishClass.PROTECTION, WishClass.COMFORT}),
        apply=_raises,
        function=function,
        **extra,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("wish_class", [WishClass.PROTECTION, WishClass.COMFORT])
def test_constraint_that_raises_without_a_cautious_result_stops_the_wish(
    wish_class: WishClass,
) -> None:
    """It cannot say how far it would have limited, so the wish is not executed."""
    arbiter = _arbiter(constraints=(*BUILT_IN_CONSTRAINTS, _broken()))

    decision = _decide(arbiter, WORLDS[wish_class]())

    assert decision.winning_wish is not None
    assert decision.winning_wish.wish_class is wish_class
    assert decision.constraints == (
        ConstraintResult(
            Constraint.VENTILATION_FLOOR,
            ReasonCode.CONSTRAINT_FAILED,
            (MemberTarget(LEFT, None),),
        ),
    )
    assert decision.targets == (MemberTarget(LEFT, None),)
    assert decision.gate is None
    assert decision.faults == (
        _fault(Constraint.VENTILATION_FLOOR, FunctionId.VENTILATION),
    )
    assert decision.faults[0].stage is EvaluationStage.CONSTRAINT


def test_constraint_that_raises_never_stops_fire() -> None:
    """Fire is subject to no constraint at all, so none is even asked."""
    arbiter = _arbiter(constraints=(*BUILT_IN_CONSTRAINTS, _broken()))

    decision = _decide(arbiter, fire())

    assert decision.target == FULLY_OPEN
    assert decision.constraints == ()
    assert decision.faults == ()
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND


def test_constraint_that_raises_applies_the_cautious_result_it_states() -> None:
    """A floor of 30 it can always state: the closing stops there."""

    def floor(constraint: ConstraintInput) -> ConstraintResult:
        return ConstraintResult(
            Constraint.VENTILATION_FLOOR,
            ReasonCode.VENTILATION_FLOOR,
            tuple(
                MemberTarget(target.member_id, Position(30))
                for target in constraint.targets
            ),
        )

    arbiter = _arbiter(constraints=(*BUILT_IN_CONSTRAINTS, _broken(cautious=floor)))

    decision = _decide(arbiter, storm())

    assert decision.constraints[-1] == ConstraintResult(
        Constraint.VENTILATION_FLOOR,
        ReasonCode.CONSTRAINT_FAILED,
        (MemberTarget(LEFT, Position(30)),),
    )
    assert decision.target == Position(30)
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND
    assert len(decision.faults) == 1


def test_cautious_result_that_limits_nothing_is_recorded_all_the_same() -> None:
    """The record shows the failure also where nothing had to be limited."""
    arbiter = _arbiter(
        constraints=(*BUILT_IN_CONSTRAINTS, _broken(cautious=lambda _input: None))
    )

    decision = _decide(arbiter, day())

    assert decision.constraints[-1].reason is ReasonCode.CONSTRAINT_FAILED
    assert decision.target == FULLY_OPEN
    assert len(decision.faults) == 1


def test_cautious_result_that_raises_too_stops_the_wish_and_both_are_reported() -> None:
    """Without any result the constraint can state, nothing moves."""
    arbiter = _arbiter(constraints=(*BUILT_IN_CONSTRAINTS, _broken(cautious=_raises)))

    decision = _decide(arbiter, day())

    assert decision.targets == (MemberTarget(LEFT, None),)
    assert decision.gate is None
    expected = _fault(Constraint.VENTILATION_FLOOR, FunctionId.VENTILATION)
    assert decision.faults == (expected, expected)


def test_constraint_answer_that_is_no_result_counts_as_raised() -> None:
    """A constraint that returns a bare position has failed; the wish is not executed."""
    confused = replace(_broken(), apply=lambda _input: Position(30))  # type: ignore[arg-type,return-value]
    arbiter = _arbiter(constraints=(*BUILT_IN_CONSTRAINTS, confused))

    decision = _decide(arbiter, day())

    assert decision.gate is None
    (fault,) = decision.faults
    assert fault.error == "TypeError"


def test_later_constraints_still_apply_after_one_that_raised() -> None:
    """The broken floor states nothing to limit; frost behind it still limits to 90."""
    config = window(frost=FrostSettings(source="outdoor_temperature"))
    arbiter = _arbiter(
        constraints=(*BUILT_IN_CONSTRAINTS, _broken(cautious=lambda _input: None))
    )

    decision = _decide(
        arbiter, day(outdoor_temperature=SourceValue.of(-3.0)), config=config
    )

    assert [result.reason for result in decision.constraints] == [
        ReasonCode.CONSTRAINT_FAILED,
        ReasonCode.FROST_LIMIT,
    ]
    assert decision.target == FrostSettings().position


def test_check_of_the_current_position_that_raises_grants_no_exemption() -> None:
    """A violated floor exempts from the minimum change; an exception exempts nothing."""
    quiet = ConstraintRegistration(
        constraint=Constraint.VENTILATION_FLOOR,
        applies_to=frozenset({WishClass.COMFORT}),
        apply=lambda _input: None,
        function=FunctionId.VENTILATION,
        violated_by_position=_raises,
    )
    arbiter = _arbiter(constraints=(*BUILT_IN_CONSTRAINTS, quiet))
    wanted = day(shading_position=SourceValue.of(53))

    decision = _decide(arbiter, wanted)

    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.MIN_CHANGE
    assert decision.faults == (
        _fault(Constraint.VENTILATION_FLOOR, FunctionId.VENTILATION),
    )
    # The same check answering "violated" would have let the small movement pass.
    violated = replace(quiet, violated_by_position=lambda _input: True)
    exempt = _decide(_arbiter(constraints=(*BUILT_IN_CONSTRAINTS, violated)), wanted)
    assert exempt.gate is not None
    assert exempt.gate.kind is GateKind.SEND


# --- The frost constraint: the first known case ------------------------------------

FROSTY = window(frost=FrostSettings(source="outdoor_temperature"))
FROST_THAT_RAISES = replace(FROST_CONSTRAINT, apply=_raises)


def test_frost_constraint_that_raises_keeps_limiting_to_the_frost_position() -> None:
    """The exception is forced through a stub, because the reader no longer raises."""
    arbiter = _arbiter(constraints=(DIRECTION_CONSTRAINT, FROST_THAT_RAISES))
    mild = day(outdoor_temperature=SourceValue.of(6.0))

    decision = _decide(arbiter, mild, config=FROSTY)

    assert decision.constraints == (
        ConstraintResult(
            Constraint.FROST_PROTECTION,
            ReasonCode.CONSTRAINT_FAILED,
            (MemberTarget(LEFT, FrostSettings().position),),
        ),
    )
    assert decision.target == FrostSettings().position
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND
    assert decision.faults == (_fault(Constraint.FROST_PROTECTION, FunctionId.FROST),)


def test_frost_constraint_that_raises_never_limits_closing() -> None:
    """The most restrictive result it could have produced for a closing is none."""
    arbiter = _arbiter(constraints=(DIRECTION_CONSTRAINT, FROST_THAT_RAISES))

    decision = _decide(
        arbiter, storm(), config=replace(FROSTY, frost_applies_to_protection=True)
    )

    assert decision.target == FULLY_CLOSED
    assert decision.constraints[-1].reason is ReasonCode.CONSTRAINT_FAILED
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND


def test_frost_constraint_that_raises_keeps_what_a_person_decided() -> None:
    """Not configured, not for protection, waived: no valid evaluation would limit."""
    arbiter = _arbiter(constraints=(DIRECTION_CONSTRAINT, FROST_THAT_RAISES))

    unconfigured = _decide(arbiter, day())

    assert unconfigured.target == FULLY_OPEN
    assert unconfigured.constraints[-1].reason is ReasonCode.CONSTRAINT_FAILED


def test_frost_source_that_delivers_text_no_longer_raises() -> None:
    """The case of the review, through the real constraint: limited, no fault."""
    decision = _decide(
        _arbiter(), day(outdoor_temperature=SourceValue.of("cold")), config=FROSTY
    )

    assert [result.reason for result in decision.constraints] == [
        ReasonCode.FROST_LIMIT_SOURCE_BLIND
    ]
    assert decision.target == FrostSettings().position
    assert decision.faults == ()


# --- Gate rules the fire bypass skips -----------------------------------------------


@pytest.mark.parametrize(
    ("rule", "held_back"),
    [
        (GateRule.OPERATING_MODE, {WishClass.PROTECTION, WishClass.COMFORT}),
        (GateRule.PAUSE, {WishClass.COMFORT}),
        (GateRule.PERSON_AT_WINDOW_DAM, {WishClass.PROTECTION, WishClass.COMFORT}),
        (GateRule.MANUAL_OVERRIDE_DAM, {WishClass.COMFORT}),
        (GateRule.MOTOR_PROTECTION, {WishClass.COMFORT}),
    ],
)
@pytest.mark.parametrize("wish_class", ALL)
def test_rule_of_the_bypass_that_raises_holds_back_what_it_applies_to_never_fire(
    rule: GateRule, held_back: set[WishClass], wish_class: WishClass
) -> None:
    """The restriction applies to the classes of the rule; a fire wish is never asked."""
    arbiter = _arbiter(gate_rules=_gate_rules(rule))

    decision = _decide(arbiter, WORLDS[wish_class]())

    assert decision.winning_wish is not None
    assert decision.winning_wish.wish_class is wish_class
    assert decision.gate is not None
    if wish_class in held_back:
        assert decision.gate.kind is GateKind.DEFER
        assert decision.gate.reason is ReasonCode.GATE_RULE_FAILED
        assert decision.gate.rule is rule
        assert decision.gate.reevaluate_no_later_than == (
            NOW + window().reevaluate_after
        )
        assert [fault.place for fault in decision.faults] == [rule]
        assert decision.faults[0].stage is EvaluationStage.GATE_RULE
    else:
        assert decision.gate.kind is GateKind.SEND
        assert decision.faults == ()


def test_fire_passes_although_every_rule_of_the_bypass_raises() -> None:
    """Including the deferral of "movement in flight", the skipped part of that rule."""
    skipped = tuple(
        replace(entry, evaluate=_raises)
        if WishClass.FIRE not in entry.applies_to
        else entry
        for entry in BUILT_IN_GATE_RULES
    )
    arbiter = _arbiter(gate_rules=skipped, constraints=(_broken(),))

    decision = _decide(arbiter, fire(), controls=on_level("global", paused=True))

    assert decision.target == FULLY_OPEN
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND
    assert decision.faults == ()


# --- Gate rules the fire bypass does not skip ---------------------------------------


@pytest.mark.parametrize("controls", [ARMED, DRY_RUN], ids=["armed", "dry-run"])
@pytest.mark.parametrize("wish_class", ALL)
def test_maintenance_lock_that_raises_holds_back_every_wish_fire_included(
    wish_class: WishClass, controls: Controls
) -> None:
    """It protects a person working at the shutter: nothing moves, not even at fire."""
    arbiter = _arbiter(gate_rules=_gate_rules(GateRule.MAINTENANCE_LOCK))

    decision = _decide(arbiter, WORLDS[wish_class](), controls=controls)

    assert decision.winning_wish is not None
    assert decision.winning_wish.wish_class is wish_class
    assert decision.target == TARGETS[wish_class]
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.DEFER
    assert decision.gate.reason is ReasonCode.GATE_RULE_FAILED
    assert decision.gate.rule is GateRule.MAINTENANCE_LOCK
    assert decision.gate.dry_run is controls.dry_run
    assert decision.faults == (_fault(GateRule.MAINTENANCE_LOCK, None),)


@pytest.mark.parametrize("controls", [ARMED, DRY_RUN], ids=["armed", "dry-run"])
def test_dry_run_rule_that_raises_sends_a_pending_fire_wish(controls: Controls) -> None:
    """An escape route that stays closed in a fire is the greater evil."""
    arbiter = _arbiter(gate_rules=_gate_rules(GateRule.DRY_RUN))
    world = snapshot(sources=fire(), controls=controls)

    decision = arbiter.recompute(window(), world)

    assert decision.winning_wish is not None
    assert decision.winning_wish.wish_class is WishClass.FIRE
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND
    assert decision.gate.reason is ReasonCode.SENT
    assert decision.faults == (_fault(GateRule.DRY_RUN, None),)
    # What the decision leaves behind: nothing simulated, the state as it was.
    assert Engine(window(), arbiter).state_after(world, decision) == world.state


@pytest.mark.parametrize("controls", [ARMED, DRY_RUN], ids=["armed", "dry-run"])
@pytest.mark.parametrize("wish_class", [WishClass.PROTECTION, WishClass.COMFORT])
def test_dry_run_rule_that_raises_holds_back_every_wish_but_fire(
    wish_class: WishClass, controls: Controls
) -> None:
    """For every other class the cautious result stays "do not send"."""
    arbiter = _arbiter(gate_rules=_gate_rules(GateRule.DRY_RUN))
    world = snapshot(sources=WORLDS[wish_class](), controls=controls)

    decision = arbiter.recompute(window(), world)

    assert decision.gate is not None
    assert decision.gate.kind is GateKind.DEFER
    assert decision.gate.reason is ReasonCode.GATE_RULE_FAILED
    assert decision.gate.rule is GateRule.DRY_RUN
    assert decision.gate.would_send == ()
    assert decision.gate.dry_run is controls.dry_run
    assert decision.faults == (_fault(GateRule.DRY_RUN, None),)
    assert Engine(window(), arbiter).state_after(world, decision) == world.state


@pytest.mark.parametrize(
    "rule",
    [
        GateRule.NO_MEMBER_CAN_EXECUTE,
        GateRule.TARGET_REACHED,
        GateRule.MOVEMENT_IN_FLIGHT,
    ],
)
@pytest.mark.parametrize("wish_class", ALL)
def test_every_other_rule_fire_does_not_skip_holds_back_like_the_lock(
    rule: GateRule, wish_class: WishClass
) -> None:
    """What is possible, what is already true, and a command that is still pending."""
    arbiter = _arbiter(gate_rules=_gate_rules(rule))

    decision = _decide(arbiter, WORLDS[wish_class]())

    assert decision.gate is not None
    assert decision.gate.kind is GateKind.DEFER
    assert decision.gate.reason is ReasonCode.GATE_RULE_FAILED
    assert decision.gate.rule is rule
    assert decision.faults[0] == _fault(rule, None)


def test_rule_that_raises_behind_a_rule_that_applies_is_never_asked() -> None:
    """The first rule that applies decides; the broken dry-run rule is not reached."""
    arbiter = _arbiter(gate_rules=_gate_rules(GateRule.DRY_RUN))

    decision = _decide(arbiter, day(), controls=on_level("window", paused=True))

    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.PAUSED
    assert decision.faults == ()


# --- Nothing leaves, nothing changes between two runs -------------------------------


def test_everything_raises_at_once_and_a_decision_still_comes_back() -> None:
    """Layers, constraints and gate rules: no exception leaves the recompute."""
    arbiter = _arbiter(
        layers=_layers(Layer.SLEEP, Layer.SHADING),
        constraints=(
            replace(DIRECTION_CONSTRAINT, apply=_raises),
            FROST_THAT_RAISES,
            _broken(violated_by_position=_raises),
        ),
        gate_rules=tuple(
            replace(entry, evaluate=_raises) for entry in BUILT_IN_GATE_RULES
        ),
    )

    for wish_class in ALL:
        decision = _decide(arbiter, WORLDS[wish_class](), config=FROSTY)

        assert decision.winning_wish is not None
        assert decision.winning_wish.wish_class is wish_class
        assert decision.faults
        if wish_class is WishClass.FIRE:
            assert decision.gate is not None
            assert decision.gate.rule is GateRule.MAINTENANCE_LOCK
        else:
            assert decision.gate is None


def test_same_snapshot_gives_the_same_decision_also_with_faults() -> None:
    """Determinism is kept: the exception objects differ, the decisions are equal."""
    arbiter = _arbiter(
        layers=_layers(Layer.SLEEP),
        constraints=(*BUILT_IN_CONSTRAINTS, _broken(cautious=lambda _input: None)),
        gate_rules=_gate_rules(GateRule.PAUSE),
    )

    first = _decide(arbiter, day(sleep=SourceValue.of(True)))
    second = _decide(arbiter, day(sleep=SourceValue.of(True)))

    assert first == second
    assert hash(first.faults) == hash(second.faults)
    assert len(first.faults) == 3  # noqa: PLR2004 - a layer, a constraint, a rule
    assert first.faults[0].exception is not second.faults[0].exception


def test_only_exceptions_are_caught_never_a_request_to_stop() -> None:
    """``KeyboardInterrupt`` and the like are no programming errors of a layer."""

    def interrupted(_config: WindowConfig, _world: WorldSnapshot) -> Wish:
        raise KeyboardInterrupt

    arbiter = build_arbiter([registered(Layer.SLEEP, interrupted)])

    with pytest.raises(KeyboardInterrupt):
        _decide(arbiter, day())


def test_kit_declares_the_function_of_every_layer_it_breaks() -> None:
    """The faults above name functions; the kit has to know them."""
    assert {entry.layer for entry in STUB_LAYERS} <= set(FUNCTION_OF)
