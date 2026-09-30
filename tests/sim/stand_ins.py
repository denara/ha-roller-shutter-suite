"""Test-only stand-ins for blocks that do not exist yet: C08 and C11.

**These are not the real features.** Situations 4 and 5 of the specification
need lockout protection (block C08), and situation 6 needs sleep mode (block
C11). Until those blocks exist, the tests and the scenarios of block C07 use
these stand-ins, and only these. When C08 and C11 arrive, their real
constraint and layer replace them here, and the tests keep their outcome.

| Stand-in | For | Source | Answer |
|---|---|---|---|
| lockout | C08, constraint 3 | ``door`` (bool, on = open), ``tamper`` (bool) | door open: never lower (``lockout_door_open``); tamper on: void (``lockout_void_tamper``) |
| sleep | C11, layer 3 | ``sleep`` (bool) | on: the night position (0), ``sleep_mode``; off: inactive |

The lockout stand-in states the function ``lockout`` (it falls back), as the
real constraint will. A door source without a value counts as open, as
section 2.2 says for the real one.
"""

from datetime import datetime
from typing import Final

from custom_components.roller_shutter_suite.core.arbiter import (
    ConstraintInput,
    ConstraintRegistration,
    LayerRegistration,
)
from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    Constraint,
    ConstraintResult,
    FunctionId,
    Layer,
    MemberTarget,
    WindowConfig,
    Wish,
    WishClass,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode

DOOR_SOURCE: Final = "door"
TAMPER_SOURCE: Final = "tamper"
SLEEP_SOURCE: Final = "sleep"
SLEEP_SINCE: Final = "sleep_since"
"""A text source with the instant sleep mode was switched on: its trigger."""


def _switch(world: WorldSnapshot, key: str) -> bool | None:
    value = world.sources.get(key)
    if value is None or not value.has_value or not isinstance(value.value, bool):
        return None
    return value.value


def _lockout(constraint: ConstraintInput) -> ConstraintResult | None:
    """Stand-in for C08: while the door is open, never lower; void with tamper."""
    world = constraint.snapshot
    if DOOR_SOURCE not in world.sources:
        return None
    if _switch(world, TAMPER_SOURCE) is True:
        return ConstraintResult(
            Constraint.LOCKOUT_PROTECTION,
            ReasonCode.LOCKOUT_VOID_TAMPER,
            constraint.targets,
        )
    if _switch(world, DOOR_SOURCE) is False:
        return None
    reported = constraint.current_positions
    targets = tuple(
        MemberTarget(target.member_id, None)
        if target.position is not None
        and (
            (position := reported.get(target.member_id)) is None
            or target.position < position
        )
        else target
        for target in constraint.targets
    )
    if targets == constraint.targets:
        return None
    return ConstraintResult(
        Constraint.LOCKOUT_PROTECTION, ReasonCode.LOCKOUT_DOOR_OPEN, targets
    )


LOCKOUT_STAND_IN: Final = ConstraintRegistration(
    constraint=Constraint.LOCKOUT_PROTECTION,
    applies_to=frozenset({WishClass.PROTECTION, WishClass.COMFORT}),
    apply=_lockout,
    function=FunctionId.LOCKOUT,
)
"""STAND-IN for lockout protection of block C08; test-only."""


def _sleep(_config: WindowConfig, world: WorldSnapshot) -> Wish:
    """Stand-in for C11: the night position while the sleep source is on."""
    if SLEEP_SOURCE not in world.sources:
        return Wish.no_opinion(Layer.SLEEP, ReasonCode.NOT_CONFIGURED)
    switch = _switch(world, SLEEP_SOURCE)
    if switch is None:
        return Wish.no_opinion(Layer.SLEEP, ReasonCode.INPUT_UNAVAILABLE)
    if not switch:
        return Wish.no_opinion(Layer.SLEEP, ReasonCode.INACTIVE)
    since = world.sources.get(SLEEP_SINCE)
    at = (
        datetime.fromisoformat(str(since.value))
        if since is not None and since.has_value
        else world.time
    )
    return Wish.target(Layer.SLEEP, ReasonCode.SLEEP_MODE, FULLY_CLOSED).triggered(at)


SLEEP_STAND_IN: Final = LayerRegistration(Layer.SLEEP, _sleep, FunctionId.SLEEP)
"""STAND-IN for the sleep layer of block C11; test-only."""
