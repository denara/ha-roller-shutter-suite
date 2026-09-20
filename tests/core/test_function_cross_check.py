"""Cross-check: the functions the settings know and the functions the arbiter runs.

The resolver of the settings disables a comfort function for a window when a
stored setting of it is faulty, and the arbiter then does not ask the layers of
that function. Both sides name functions by ``FunctionId``. This test makes
sure they mean the same things:

(a) every comfort layer and every constraint registered in the arbiter that
    ``build_arbiter()`` returns declares a member of ``FunctionId``;
(b) every comfort function that has at least one setting has at least one
    registered layer or constraint. Otherwise the resolver switches something
    off that the arbiter keeps running under another name, or nothing listens
    at all.

Feature layers arrive block by block. A comfort function that has settings
before its layer is built stands in ``NOT_BUILT_YET``. That list can only
shrink: the test fails for an entry that is no longer needed, and it fails for
a function with settings that has neither a listener nor an entry.
"""

from collections.abc import Iterable

import pytest

from custom_components.roller_shutter_suite.core.arbiter import (
    Arbiter,
    ConstraintRegistration,
)
from custom_components.roller_shutter_suite.core.engine import build_arbiter
from custom_components.roller_shutter_suite.core.model import (
    Constraint,
    FunctionClass,
    FunctionId,
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
"""Comfort functions with settings whose layer or constraint is still to come."""

BELONGS_TO_THE_WISH = frozenset({Constraint.DIRECTION})
"""Constraints that state no function: they belong to the function of the wish."""


def listeners(arbiter: Arbiter) -> frozenset[FunctionId]:
    """Return the functions that a registered layer or constraint declares."""
    declared = [registration.function for registration in arbiter.layers]
    declared += [registration.function for registration in arbiter.constraints]
    return frozenset(function for function in declared if function is not None)


def check_declarations(arbiter: Arbiter) -> None:
    """Fail for a comfort layer or a constraint whose function is not a ``FunctionId``."""
    for layer in arbiter.layers:
        if layer.layer.wish_class is WishClass.COMFORT:
            assert isinstance(layer.function, FunctionId), layer.layer
            assert layer.function.function_class is FunctionClass.COMFORT, layer.layer
    for constraint in arbiter.constraints:
        if constraint.constraint in BELONGS_TO_THE_WISH:
            assert constraint.function is None, constraint.constraint
        else:
            assert isinstance(constraint.function, FunctionId), constraint.constraint


def check_listeners(
    arbiter: Arbiter,
    with_settings: Iterable[FunctionId],
    not_built_yet: Iterable[FunctionId],
) -> None:
    """Fail for a comfort function nobody listens to, and for a needless entry."""
    listening = listeners(arbiter)
    waiting = frozenset(not_built_yet)
    comfort = {
        function
        for function in with_settings
        if function.function_class is FunctionClass.COMFORT
    }
    for function in sorted(comfort - listening - waiting):
        raise AssertionError(
            f"the comfort function {function.value!r} has settings, but no "
            "registered layer or constraint declares it. Register one with this "
            "function, or add it to NOT_BUILT_YET in "
            "tests/core/test_function_cross_check.py until its block is built."
        )
    for function in sorted(waiting & listening):
        raise AssertionError(
            f"{function.value!r} stands in NOT_BUILT_YET, but a layer or a "
            "constraint declares it now: remove the entry"
        )
    for function in sorted(waiting - comfort):
        raise AssertionError(
            f"{function.value!r} stands in NOT_BUILT_YET, but it is no comfort "
            "function with settings: remove the entry"
        )


def test_every_registered_comfort_layer_and_constraint_declares_a_function() -> None:
    """(a), for the arbiter of the integration and for the stub layers."""
    check_declarations(build_arbiter())
    check_declarations(build_arbiter(STUB_LAYERS))


def test_every_comfort_function_with_settings_has_a_listener() -> None:
    """(b), for the arbiter of the integration."""
    check_listeners(build_arbiter(), functions_with_settings(), NOT_BUILT_YET)


# --- The check itself, shown with the stub layers -----------------------------------

STUBS = build_arbiter(STUB_LAYERS)
"""Listens to sleep, shading and schedule, and through the frost constraint to frost."""


def test_the_stub_arbiter_listens_to_what_it_declares() -> None:
    """Layers and constraints both count as listeners."""
    assert listeners(STUBS) == {
        FunctionId.SLEEP,
        FunctionId.SHADING,
        FunctionId.SCHEDULE,
        FunctionId.FROST,
    }
    check_listeners(STUBS, {FunctionId.SCHEDULE, FunctionId.SHADING}, ())


def test_a_comfort_function_with_settings_and_without_a_listener_fails() -> None:
    """Unless it stands in the list of what is not built yet."""
    with_settings = {FunctionId.SCHEDULE, FunctionId.PRIVACY}

    with pytest.raises(AssertionError, match=r"'privacy' has settings, but no"):
        check_listeners(STUBS, with_settings, ())
    check_listeners(STUBS, with_settings, {FunctionId.PRIVACY})


def test_a_protection_function_needs_no_listener_here() -> None:
    """The resolver never disables it, so nothing can go unheard."""
    check_listeners(STUBS, {FunctionId.LOCKOUT, FunctionId.FIRE}, ())


def test_the_list_of_what_is_not_built_yet_can_only_shrink() -> None:
    """An entry whose layer exists, or that has no settings, fails."""
    with pytest.raises(
        AssertionError, match=r"'shading' stands in NOT_BUILT_YET, but a"
    ):
        check_listeners(STUBS, {FunctionId.SHADING}, {FunctionId.SHADING})
    with pytest.raises(AssertionError, match=r"'privacy' stands in .* no comfort func"):
        check_listeners(STUBS, (), {FunctionId.PRIVACY})
    with pytest.raises(AssertionError, match=r"'lockout' stands in .* no comfort func"):
        check_listeners(STUBS, {FunctionId.LOCKOUT}, {FunctionId.LOCKOUT})


def test_a_constraint_counts_as_a_listener() -> None:
    """The ventilation floor will be a constraint, not a layer."""
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
