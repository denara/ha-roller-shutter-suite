"""Constraint 2: the sleep-room exception (D4).

Per window, a protection event can be marked "must not open this window while
sleep mode is active" (``WindowConfig.protection_sleep_exception``, the
identifiers of the events). While the winning protection wish comes from such
an event and sleep mode is active, the window is **never raised**: a member
whose target lies above where it stands is pinned. Closing is not limited.
Fire ignores the exception (no constraint applies to fire); comfort wishes
are not concerned.

**"Sleep mode is active"** is judged from the answer of the sleep layer in
this very recompute: the sleep layer wants a position. There is no sleep
source in the window configuration; the sleep layer is built by block C11,
and the arbiter hands every layer's answer to the constraints
(``ConstraintInput.answers``).

A member that reports no position cannot be judged; a target above fully
closed could be a raise, so such a member is pinned: the person asked that
this event never opens the window during sleep. A faulty stored exception is
"no exception" for the window (the fault value): protection wins over sleep.
"""

from typing import Final

from custom_components.roller_shutter_suite.core.arbiter.registry import (
    ConstraintInput,
    ConstraintRegistration,
)
from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    Constraint,
    ConstraintResult,
    FunctionId,
    Layer,
    MemberTarget,
    WishClass,
    WishKind,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode


def sleep_mode_active(constraint: ConstraintInput) -> bool:
    """Return whether the sleep layer wants a position in this recompute."""
    return any(
        answer.kind is WishKind.TARGET for answer in constraint.answers_of(Layer.SLEEP)
    )


def _marked(constraint: ConstraintInput) -> bool:
    subject = constraint.wish.subject
    return (
        subject is not None
        and subject.event_id is not None
        and subject.event_id in constraint.config.protection_sleep_exception
    )


def _never_raise(constraint: ConstraintInput) -> ConstraintResult | None:
    reported = constraint.current_positions
    targets: list[MemberTarget] = []
    for target in constraint.targets:
        position = reported.get(target.member_id)
        raises = target.position is not None and (
            target.position > position
            if position is not None
            else target.position > FULLY_CLOSED
        )
        targets.append(MemberTarget(target.member_id, None) if raises else target)
    if tuple(targets) == constraint.targets:
        return None
    return ConstraintResult(
        Constraint.SLEEP_ROOM_EXCEPTION,
        ReasonCode.SLEEP_EXCEPTION_NO_OPEN,
        tuple(targets),
    )


def _apply(constraint: ConstraintInput) -> ConstraintResult | None:
    if not _marked(constraint) or not sleep_mode_active(constraint):
        return None
    return _never_raise(constraint)


def _apply_cautiously(constraint: ConstraintInput) -> ConstraintResult | None:
    """Return the most restrictive result: what applies if ``_apply`` raised.

    As if the event were marked and sleep mode active, without asking either:
    no member is raised. A window without any sleep-room exception has none
    to keep.
    """
    if not constraint.config.protection_sleep_exception:
        return None
    return _never_raise(constraint)


SLEEP_EXCEPTION_CONSTRAINT: Final = ConstraintRegistration(
    constraint=Constraint.SLEEP_ROOM_EXCEPTION,
    applies_to=frozenset({WishClass.PROTECTION}),
    apply=_apply,
    function=FunctionId.PROTECTION_EVENTS,
    cautious=_apply_cautiously,
)
"""Protection wishes of marked events only; fire never, comfort never."""
