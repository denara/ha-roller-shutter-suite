"""Cross-check: the functions the settings know and the functions the arbiter runs.

The resolver of the settings pauses a function for a window when a stored
setting of it is faulty, and the arbiter then does not ask the layer of that
function. Both sides name functions by ``FunctionId``. These tests make sure
they mean the same things.

**Nothing that restricts movement can be paused.** What decides is the
direction of the effect. A paused layer creates no wish: less movement, the
cautious side. A paused constraint or gate rule removes a restriction: more
movement, a shutter closing completely in front of a tilted window because of a
data fault. So the function of every registered constraint and gate rule has
the fault behavior "fall back". ``check_restrictions`` fails otherwise.

**Somebody listens to every function that has settings.**

- Every function that is paused on a fault and has settings has a registered
  LAYER. Otherwise the resolver pauses something that nothing stops doing.
- Every function that falls back and has settings has a layer, a constraint or
  a gate rule. Otherwise the settings configure nothing.

Feature blocks arrive one by one. A function that has settings before its
block is built stands in ``NOT_BUILT_YET``. That list can only shrink: the
test fails for an entry that is no longer needed, and it fails for a function
with settings that has neither a listener nor an entry.
"""

from collections.abc import Iterable

import pytest

from custom_components.roller_shutter_suite.core.arbiter import (
    Arbiter,
    ConstraintRegistration,
    GateRuleRegistration,
)
from custom_components.roller_shutter_suite.core.engine import build_arbiter
from custom_components.roller_shutter_suite.core.model import (
    Constraint,
    FaultBehavior,
    FunctionId,
    GateRule,
    WishClass,
)
from tests.core.arbiter_kit import STUB_LAYERS


def functions_with_settings() -> frozenset[FunctionId]:
    """Return the functions that have at least one setting in the settings registry.

    THE ONE PLACE TO CONNECT. The settings registry (``core/settings``) exposes
    a pure function that returns this set. It is not on the main branch yet;
    once it is, this function returns its result and nothing else changes.
    Until then no function has a setting here.
    """
    return frozenset()


NOT_BUILT_YET: frozenset[FunctionId] = frozenset()
"""Functions with settings whose layer, constraint or gate rule is still to come."""

BELONGS_TO_THE_WISH = frozenset({Constraint.DIRECTION})
"""Constraints that state no function: they belong to the function of the wish.

Such a constraint has no settings of its own.
"""


def check_declarations(arbiter: Arbiter) -> None:
    """Fail for a registration whose function is not what its kind requires."""
    for layer in arbiter.layers:
        if layer.layer.wish_class is WishClass.COMFORT:
            assert isinstance(layer.function, FunctionId), layer.layer
            assert layer.function.fault_behavior is FaultBehavior.PAUSE, layer.layer
        else:
            assert layer.function is None or (
                isinstance(layer.function, FunctionId)
                and layer.function.fault_behavior is FaultBehavior.FALL_BACK
            ), layer.layer
    for constraint in arbiter.constraints:
        if constraint.constraint in BELONGS_TO_THE_WISH:
            assert constraint.function is None, constraint.constraint
        else:
            assert isinstance(constraint.function, FunctionId), constraint.constraint
    for rule in arbiter.gate_rules:
        assert rule.function is None or isinstance(rule.function, FunctionId), rule.rule


def check_restrictions(
    registrations: Iterable[ConstraintRegistration | GateRuleRegistration],
) -> None:
    """Fail for a constraint or a gate rule whose function can be paused."""
    for registration in registrations:
        function = registration.function
        if function is not None and function.fault_behavior is not (
            FaultBehavior.FALL_BACK
        ):
            place = (
                registration.constraint
                if isinstance(registration, ConstraintRegistration)
                else registration.rule
            )
            raise AssertionError(
                f"{place.value!r} restricts movement but declares the function "
                f"{function.value!r}, which is paused on a fault. Pausing a "
                "restriction means MORE movement because of a data fault. A "
                "function that a constraint or a gate rule belongs to has the "
                "fault behavior 'fall_back'."
            )


def check_listeners(
    arbiter: Arbiter,
    with_settings: Iterable[FunctionId],
    not_built_yet: Iterable[FunctionId],
) -> None:
    """Fail for a function with settings nobody listens to, and for a needless entry."""
    layers = {entry.function for entry in arbiter.layers}
    restrictions = {entry.function for entry in arbiter.constraints} | {
        entry.function for entry in arbiter.gate_rules
    }
    configured = frozenset(with_settings)
    waiting = frozenset(not_built_yet)

    def heard(function: FunctionId) -> bool:
        if function.fault_behavior is FaultBehavior.PAUSE:
            return function in layers
        return function in layers or function in restrictions

    for function in sorted(configured - waiting):
        if not heard(function):
            needed = (
                "a registered layer"
                if function.fault_behavior is FaultBehavior.PAUSE
                else "a registered layer, constraint or gate rule"
            )
            raise AssertionError(
                f"the function {function.value!r} has settings, but it has no "
                f"listener: it needs {needed} that declares it. Register one, or "
                "add the function to NOT_BUILT_YET in "
                "tests/core/test_function_cross_check.py until its block is built."
            )
    for function in sorted(waiting):
        if function not in configured:
            raise AssertionError(
                f"{function.value!r} stands in NOT_BUILT_YET, but it has no "
                "settings: remove the entry"
            )
        if heard(function):
            raise AssertionError(
                f"{function.value!r} stands in NOT_BUILT_YET, but it has a "
                "listener now: remove the entry"
            )


# --- The arbiter of the integration -------------------------------------------------


def test_every_registration_declares_a_function_of_the_closed_list() -> None:
    """For the arbiter of the integration and for the stub layers of the test kit."""
    check_declarations(build_arbiter())
    check_declarations(build_arbiter(STUB_LAYERS))


def test_no_function_of_a_constraint_or_a_gate_rule_can_be_paused() -> None:
    """For the arbiter of the integration and for the registrations of the test kit."""
    for arbiter in (build_arbiter(), build_arbiter(STUB_LAYERS)):
        check_restrictions(arbiter.constraints)
        check_restrictions(arbiter.gate_rules)
    declared = {
        entry.function for entry in build_arbiter().gate_rules if entry.function
    } | {entry.function for entry in build_arbiter().constraints if entry.function}
    assert declared == {
        FunctionId.FROST,
        FunctionId.MOTOR_PROTECTION,
        FunctionId.MANUAL_OVERRIDE,
    }


def test_every_function_with_settings_has_a_listener() -> None:
    """For the arbiter of the integration."""
    check_listeners(build_arbiter(), functions_with_settings(), NOT_BUILT_YET)


# --- The checks themselves, shown with stubs ----------------------------------------

STUBS = build_arbiter(STUB_LAYERS)


def _corrupted[R: (ConstraintRegistration, GateRuleRegistration)](
    registration: R, function: FunctionId
) -> R:
    """Return a registration as faulty data could produce it, past the registry."""
    object.__setattr__(registration, "function", function)
    return registration


def test_the_registry_refuses_a_restriction_with_a_function_that_can_be_paused() -> (
    None
):
    """The first line of defence; the check above is the second."""
    classes = frozenset({WishClass.COMFORT})
    with pytest.raises(ValueError, match="pausing it would mean more movement"):
        ConstraintRegistration(
            Constraint.VENTILATION_FLOOR,
            classes,
            lambda _input: None,
            FunctionId.SHADING,
        )
    with pytest.raises(ValueError, match="pausing it would mean more movement"):
        GateRuleRegistration(
            GateRule.STAGGERING, classes, lambda _gate: None, FunctionId.SCHEDULE
        )
    with pytest.raises(TypeError, match="member of 'FunctionId'"):
        GateRuleRegistration(
            GateRule.STAGGERING,
            classes,
            lambda _gate: None,
            "motor_protection",  # type: ignore[arg-type]
        )


def test_a_restriction_with_a_function_that_can_be_paused_fails_the_check() -> None:
    """A deliberately wrong stub; the message says why it matters."""
    classes = frozenset({WishClass.COMFORT})
    floor = _corrupted(
        ConstraintRegistration(
            Constraint.VENTILATION_FLOOR,
            classes,
            lambda _input: None,
            FunctionId.VENTILATION,
        ),
        FunctionId.SHADING,
    )
    staggering = _corrupted(
        GateRuleRegistration(GateRule.STAGGERING, classes, lambda _gate: None, None),
        FunctionId.SCHEDULE,
    )

    with pytest.raises(AssertionError, match=r"'ventilation_floor' restricts .* MORE"):
        check_restrictions([*STUBS.constraints, floor])
    with pytest.raises(AssertionError, match=r"'staggering' restricts .* 'schedule'"):
        check_restrictions([*STUBS.gate_rules, staggering])


def test_a_paused_function_with_settings_needs_a_layer() -> None:
    """A constraint or a gate rule does not count for it."""
    with_settings = {FunctionId.SCHEDULE, FunctionId.SHADING, FunctionId.PRIVACY}

    with pytest.raises(AssertionError, match=r"'privacy' has settings.*a registered l"):
        check_listeners(STUBS, with_settings, ())
    check_listeners(STUBS, with_settings, {FunctionId.PRIVACY})


def test_a_function_that_falls_back_is_heard_by_a_layer_a_constraint_or_a_gate_rule() -> (
    None
):
    """Fire by its layer, frost by its constraint, motor protection by its gate rule."""
    heard = {
        FunctionId.FIRE,
        FunctionId.PROTECTION_EVENTS,
        FunctionId.FROST,
        FunctionId.MOTOR_PROTECTION,
        FunctionId.MANUAL_OVERRIDE,
    }

    check_listeners(STUBS, heard, ())
    with pytest.raises(
        AssertionError, match=r"'lockout' has settings.*constraint or g"
    ):
        check_listeners(STUBS, heard | {FunctionId.LOCKOUT}, ())
    check_listeners(STUBS, heard | {FunctionId.LOCKOUT}, {FunctionId.LOCKOUT})


def test_the_list_of_what_is_not_built_yet_can_only_shrink() -> None:
    """An entry that has a listener by now, or that has no settings, fails."""
    with pytest.raises(AssertionError, match=r"'shading' stands in .* a listener now"):
        check_listeners(STUBS, {FunctionId.SHADING}, {FunctionId.SHADING})
    with pytest.raises(AssertionError, match=r"'frost' stands in .* a listener now"):
        check_listeners(STUBS, {FunctionId.FROST}, {FunctionId.FROST})
    with pytest.raises(AssertionError, match=r"'privacy' stands in .* no settings"):
        check_listeners(STUBS, (), {FunctionId.PRIVACY})


def test_a_new_constraint_is_a_listener_of_its_function() -> None:
    """The ventilation floor will be a constraint, and ventilation falls back."""
    floor = ConstraintRegistration(
        Constraint.VENTILATION_FLOOR,
        frozenset({WishClass.COMFORT}),
        lambda _input: None,
        FunctionId.VENTILATION,
    )

    with pytest.raises(AssertionError, match=r"'ventilation' has settings"):
        check_listeners(STUBS, {FunctionId.VENTILATION}, ())
    check_listeners(
        build_arbiter(STUB_LAYERS, constraints=[floor]), {FunctionId.VENTILATION}, ()
    )
