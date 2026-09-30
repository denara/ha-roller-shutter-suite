"""Constraint 7: no intermediate position during a protection event.

A half-lowered shutter offers the wind a surface and can be torn out of its
guide rails (section 6 of the brief). The target of a protection wish stays
an end position: a member whose target, after the constraints before this
one, is neither fully open nor fully closed is pinned, so the window is left
alone rather than driven halfway. If lockout protection prevents a closing,
it pins the member itself. If frost protection is configured to apply to
protection movements (``frost_applies_to_protection``), the frost position
counts as the open end position.

The return to the manual position after an event is a comfort wish and is
not concerned; fire is subject to no constraint.
"""

from typing import Final

from custom_components.roller_shutter_suite.core.arbiter.registry import (
    ConstraintInput,
    ConstraintRegistration,
)
from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    Constraint,
    ConstraintResult,
    FunctionId,
    MemberTarget,
    Position,
    WishClass,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode


def _pin_all_but(
    constraint: ConstraintInput, allowed: frozenset[Position]
) -> ConstraintResult | None:
    targets = tuple(
        target
        if target.position is None or target.position in allowed
        else MemberTarget(target.member_id, None)
        for target in constraint.targets
    )
    if targets == constraint.targets:
        return None
    return ConstraintResult(
        Constraint.NO_INTERMEDIATE_POSITION,
        ReasonCode.NO_INTERMEDIATE_POSITION,
        targets,
    )


def _apply(constraint: ConstraintInput) -> ConstraintResult | None:
    allowed = {FULLY_OPEN, FULLY_CLOSED}
    frost = constraint.config.frost
    if frost.applies_to_protection:
        allowed.add(frost.position)
    return _pin_all_but(constraint, frozenset(allowed))


def _apply_cautiously(constraint: ConstraintInput) -> ConstraintResult | None:
    """Return the most restrictive result: only the two end positions pass."""
    return _pin_all_but(constraint, frozenset({FULLY_OPEN, FULLY_CLOSED}))


NO_INTERMEDIATE_CONSTRAINT: Final = ConstraintRegistration(
    constraint=Constraint.NO_INTERMEDIATE_POSITION,
    applies_to=frozenset({WishClass.PROTECTION}),
    apply=_apply,
    function=FunctionId.PROTECTION_EVENTS,
    cautious=_apply_cautiously,
)
"""Protection wishes only; comfort and fire are not concerned."""
