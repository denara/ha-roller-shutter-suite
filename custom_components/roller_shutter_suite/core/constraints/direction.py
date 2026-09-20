"""Constraint 1: the direction a wish carries itself.

A wish can be ``raise_only`` or ``lower_only``: the morning target only raises;
evening, night and privacy only lower. A member whose target lies in the
forbidden direction is pinned: it stays where it is. A member that reports no
position cannot be judged, and its target passes; a cover without position
feedback would otherwise never follow a schedule.
"""

from typing import Final

from custom_components.roller_shutter_suite.core.arbiter.registry import (
    ConstraintInput,
    ConstraintRegistration,
)
from custom_components.roller_shutter_suite.core.model import (
    Constraint,
    ConstraintResult,
    Direction,
    MemberTarget,
    WishClass,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode


def _apply(constraint: ConstraintInput) -> ConstraintResult | None:
    direction = constraint.wish.direction
    if direction is None:
        return None
    reported = constraint.current_positions
    targets: list[MemberTarget] = []
    for target in constraint.targets:
        position = reported.get(target.member_id)
        forbidden = (
            target.position is not None
            and position is not None
            and (
                target.position < position
                if direction is Direction.RAISE_ONLY
                else target.position > position
            )
        )
        targets.append(MemberTarget(target.member_id, None) if forbidden else target)
    if tuple(targets) == constraint.targets:
        return None
    reason = (
        ReasonCode.ONLY_RAISE
        if direction is Direction.RAISE_ONLY
        else ReasonCode.ONLY_LOWER
    )
    return ConstraintResult(Constraint.DIRECTION, reason, tuple(targets))


DIRECTION_CONSTRAINT: Final = ConstraintRegistration(
    constraint=Constraint.DIRECTION,
    applies_to=frozenset({WishClass.PROTECTION, WishClass.COMFORT}),
    apply=_apply,
)
"""Applies to the wish that carries a direction; fire is subject to no constraint."""
