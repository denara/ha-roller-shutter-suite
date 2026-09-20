"""Every registered comfort layer states the trigger of its wish.

``Wish.triggered_at`` is optional in the model, and a wish without it is never
fresh: the minimum interval of motor protection holds it back although it may
be something new. A layer that forgets the trigger would therefore be late
without anybody noticing. This test notices, centrally, for every layer that
is registered in the arbiter ``build_arbiter()`` returns, also for layers that
are added later.

**If this test fails for your new layer:** add an entry for it to
``PROVOCATIONS`` below: a function that returns a window configuration and a
world snapshot in which your layer wants a position as a comfort wish. (For
the protection layer that is the return to the manual position; its wishes for
a protection event are not comfort wishes.) A layer without an entry fails the
test; it is never skipped. Then make the layer state its trigger with
``wish.triggered(at)``.
"""

from collections.abc import Callable, Mapping

import pytest

from custom_components.roller_shutter_suite.core.arbiter import (
    Arbiter,
    LayerRegistration,
)
from custom_components.roller_shutter_suite.core.engine import (
    FEATURE_LAYERS,
    build_arbiter,
)
from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    FunctionId,
    Layer,
    SourceValue,
    WindowConfig,
    Wish,
    WishClass,
    WishKind,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import (
    STUB_LAYERS,
    day,
    night,
    registered,
    snapshot,
    window,
)

type Provocation = Callable[[], tuple[WindowConfig, WorldSnapshot]]

type Part = FunctionId | Layer
"""A registration: by its function, or by its layer if it declares none."""

PROVOCATIONS: dict[Part, Provocation] = {}
"""Per registration: a situation in which it wants a position for comfort.

A layer that is registered in parts (one per function) needs one entry per
part, keyed by the function.
"""


def _part(registration: LayerRegistration) -> Part:
    return (
        registration.layer if registration.function is None else registration.function
    )


def check_triggers(arbiter: Arbiter, provocations: Mapping[Part, Provocation]) -> None:
    """Fail for a layer without an entry, without a comfort target, or without a trigger."""
    for registration in arbiter.layers:
        layer = registration.layer
        if layer.wish_class is WishClass.FIRE:
            continue  # fire has no comfort wish
        part = _part(registration)
        provoke = provocations.get(part)
        if provoke is None:
            raise AssertionError(
                f"the layer part {part.value!r} is registered, but PROVOCATIONS in "
                "tests/core/test_layer_triggers.py has no entry for it. Add a "
                "function that returns a window configuration and a snapshot in "
                "which the layer wants a position as a comfort wish."
            )
        wish = registration.evaluate(*provoke())
        if wish.kind is not WishKind.TARGET or wish.wish_class is not WishClass.COMFORT:
            raise AssertionError(
                f"the entry of PROVOCATIONS for {part.value!r} does not "
                "make it want a position as a comfort wish; it answered "
                f"{wish.kind.value!r} with {wish.reason.value!r}"
            )
        if wish.triggered_at is None:
            raise AssertionError(
                f"the layer part {part.value!r} wants a position but does not state the "
                "trigger of its wish. Set it with wish.triggered(at); see "
                "'How to add a layer' in docs/dev/arbiter.md."
            )


def test_every_registered_comfort_layer_states_the_trigger_of_its_wish() -> None:
    """The arbiter of the integration, with whatever layers are registered in it."""
    arbiter = build_arbiter()

    assert arbiter.layers == tuple(
        sorted(FEATURE_LAYERS, key=lambda entry: list(Layer).index(entry.layer))
    )
    check_triggers(arbiter, PROVOCATIONS)
    registered = {_part(registration) for registration in arbiter.layers}
    assert set(PROVOCATIONS) <= registered, "an entry for a layer that is gone"


# --- The check itself, shown with the stub layers -----------------------------------


def _world(**sources: SourceValue[bool] | SourceValue[int]) -> Provocation:
    return lambda: (window(), snapshot(sources=day(**sources)))


STUB_PROVOCATIONS: dict[Part, Provocation] = {
    FunctionId.PROTECTION_EVENTS: _world(return_to=SourceValue.of(40)),
    FunctionId.SLEEP: _world(sleep=SourceValue.of(True)),
    FunctionId.SHADING: _world(shading_position=SourceValue.of(40)),
    FunctionId.SCHEDULE: lambda: (window(), snapshot(sources=night())),
}


def _forgetful_schedule(_config: WindowConfig, _world: WorldSnapshot) -> Wish:
    return Wish.target(Layer.SCHEDULE, ReasonCode.SCHEDULE_NIGHT, FULLY_CLOSED)


def _with_schedule(registration: LayerRegistration) -> Arbiter:
    others = [entry for entry in STUB_LAYERS if entry.layer is not Layer.SCHEDULE]
    return build_arbiter([*others, registration])


def test_the_stub_layers_pass_the_check() -> None:
    """Each of them states its trigger; the fire layer is not asked."""
    check_triggers(build_arbiter(STUB_LAYERS), STUB_PROVOCATIONS)


def test_a_layer_that_forgets_its_trigger_fails_the_check() -> None:
    """The message names the layer and says what to do."""
    forgetful = _with_schedule(registered(Layer.SCHEDULE, _forgetful_schedule))

    with pytest.raises(AssertionError, match=r"'schedule' wants a position but does"):
        check_triggers(forgetful, STUB_PROVOCATIONS)


def test_a_registered_layer_without_an_entry_fails_the_check() -> None:
    """A new layer is never skipped: no entry, no pass."""
    entries: dict[Part, Provocation] = {
        part: provoke
        for part, provoke in STUB_PROVOCATIONS.items()
        if part is not FunctionId.SHADING
    }

    with pytest.raises(AssertionError, match=r"'shading' is registered, but PROVOC"):
        check_triggers(build_arbiter(STUB_LAYERS), entries)


def test_an_entry_that_provokes_no_comfort_target_fails_the_check() -> None:
    """Otherwise an entry could make the check pass without asking anything."""
    calm = STUB_PROVOCATIONS | {FunctionId.SLEEP: _world(sleep=SourceValue.of(False))}
    stormy = STUB_PROVOCATIONS | {
        FunctionId.PROTECTION_EVENTS: _world(storm=SourceValue.of(True))
    }

    with pytest.raises(AssertionError, match=r"'sleep' does not make it want"):
        check_triggers(build_arbiter(STUB_LAYERS), calm)
    with pytest.raises(
        AssertionError, match=r"'protection_events' does not make it want"
    ):
        check_triggers(build_arbiter(STUB_LAYERS), stormy)
