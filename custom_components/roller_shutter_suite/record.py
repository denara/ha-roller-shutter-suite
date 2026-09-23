"""The decision record as the status, the events and the diagnostics show it.

The core writes a decision as a tree of typed objects. This module turns it
into plain, stable data: names of enumeration members, whole numbers for
positions, ISO timestamps. It imports nothing from Home Assistant, so it can
be read and tested on its own. Three readers use it:

- the **reason sensor**: its state is :func:`active_reason`, its attributes
  are :func:`decision_attributes`, which contain nothing that changes while
  the decision stays the same;
- the **reason events**: :func:`reason_outcome` says whether a decision is
  worth an event and what the event says;
- the **diagnostics**: :func:`decision_attributes` plus the targets of every
  member (:func:`member_targets`).

**No exception is ever written out.** A fault of the arbiter's safety net
(``Decision.faults``) appears as its stage, its place, its function and the
reason code of the stage. ``EvaluationFault.exception`` and its message are
never read here, because a message can carry an entity ID.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, unique
from types import MappingProxyType
from typing import Any, Final

from .core.model import (
    ConstraintResult,
    Decision,
    EvaluationFault,
    EvaluationStage,
    GateKind,
    GateOutcome,
    MemberTarget,
    Position,
    WishKind,
)
from .core.reasons import ReasonCode

FAULT_REASONS: Final = MappingProxyType(
    {
        EvaluationStage.LAYER: ReasonCode.LAYER_FAILED,
        EvaluationStage.CONSTRAINT: ReasonCode.CONSTRAINT_FAILED,
        EvaluationStage.GATE_RULE: ReasonCode.GATE_RULE_FAILED,
    }
)
"""The reason code that stands for a fault of each stage of the safety net."""

REASON_OPTIONS: Final = tuple(code.value for code in ReasonCode)
"""Every reason code, in the order of the core: the options of the reason sensor."""

_NOT_HELD_BACK: Final = frozenset(
    {ReasonCode.SENT, ReasonCode.DUPLICATE_COMMAND, ReasonCode.TARGET_REACHED}
)
"""Gate reasons after which the wish itself explains where the window is.

A duplicate is the window's own command that is still under way: the wish
that sent it is still the reason, and the gate attributes say the rest.
"""

_NEUTRAL: Final = frozenset({ReasonCode.DUPLICATE_COMMAND})
"""Gate reasons that neither are an event nor end the outcome of the last one.

A duplicate is the command that is still under way: the outcome that fired
the last event still holds. Nothing is fired, and nothing is forgotten, so the
same would-be command in dry-run is not reported again after every expectation
window.
"""


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat()


def common_position(targets: tuple[MemberTarget, ...]) -> int | None:
    """Return the one position of all members, or ``None`` if they differ or are pinned."""
    positions = {target.position for target in targets}
    if len(positions) != 1:
        return None
    position = next(iter(positions))
    return None if position is None else position.value


def pinning_constraint(decision: Decision) -> ConstraintResult | None:
    """Return the first constraint after which no member has a target left.

    That constraint is why nothing reaches the gate although a layer wants a
    position (a closing held back by an open door, for example).
    """
    for result in decision.constraints:
        if all(target.position is None for target in result.targets):
            return result
    return None


def active_reason(decision: Decision) -> ReasonCode:
    """Return the one reason that explains best why the window is where it is.

    - Nothing wanted anything: the reason of the lowest layer, which always has
      an opinion once it is configured (``not_configured``, for example).
    - The wish went through, its command is still under way, or its target
      is reached: the reason of the wish (``schedule_night``).
    - The gate held it back: the reason of the rule (``paused``, ``dry_run``).
    - A constraint left no target: the reason of that constraint.
    - The wish holds the window where it is: the reason of the wish.
    """
    wish = decision.winning_wish
    if wish is None:
        if decision.other_layers:
            return decision.other_layers[-1].reason
        return ReasonCode.NOT_CONFIGURED
    if decision.gate is not None:
        if decision.gate.reason in _NOT_HELD_BACK:
            return wish.reason
        return decision.gate.reason
    pinned = pinning_constraint(decision)
    if pinned is not None:
        return pinned.reason
    return wish.reason


def _gate_attributes(gate: GateOutcome | None) -> dict[str, Any]:
    if gate is None:
        return {
            "gate_outcome": None,
            "gate_reason": None,
            "gate_rule": None,
            "deferred_until": None,
            "would_send": None,
        }
    return {
        "gate_outcome": gate.kind.value,
        "gate_reason": gate.reason.value,
        "gate_rule": None if gate.rule is None else gate.rule.value,
        "deferred_until": _iso(gate.until),
        "would_send": common_position(gate.would_send) if gate.would_send else None,
    }


def fault_attributes(fault: EvaluationFault) -> dict[str, Any]:
    """Return a fault as stage, place, function and reason code; never the exception."""
    return {
        "stage": fault.stage.value,
        "place": fault.place.value,
        "function": None if fault.function is None else fault.function.value,
        "reason": FAULT_REASONS[fault.stage].value,
    }


def decision_attributes(decision: Decision, *, dry_run: bool) -> dict[str, Any]:
    """Return the decision record in a compact, stable form.

    The same decision always gives the same data, and nothing in it depends
    on the time of the recompute, so a state that is written again unchanged
    is not a change. That is why the upper bound of a deferral whose end is
    not known (``reevaluate_no_later_than``) is left out: the core sets it to
    the time of the recompute plus a setting, so it moves with every
    recompute while the decision stays the same. The diagnostics show it as
    the next wake-up. ``deferred_until`` is kept: a deferral with a known end
    names an instant that the persisted state fixes (the end of a dam, the
    end of the minimum interval), not one that moves with the clock. The keys are always present; a part that the decision
    does not have is ``None`` or an empty list.
    """
    wish = decision.winning_wish
    return {
        "layer": None if wish is None else wish.layer.value,
        "wish": None if wish is None else wish.kind.value,
        "wish_class": None if wish is None else wish.wish_class.value,
        "wish_reason": None if wish is None else wish.reason.value,
        "function": (
            None
            if decision.winning_function is None
            else decision.winning_function.value
        ),
        "target": common_position(decision.targets),
        "constraints": [
            {
                "constraint": result.constraint.value,
                "reason": result.reason.value,
                "target": common_position(result.targets),
            }
            for result in decision.constraints
        ],
        **_gate_attributes(decision.gate),
        "dry_run": dry_run,
        "other_layers": [
            {
                "layer": entry.layer.value,
                "reason": entry.reason.value,
                "function": None if entry.function is None else entry.function.value,
            }
            for entry in decision.other_layers
        ],
        "faults": [fault_attributes(fault) for fault in decision.faults],
    }


def member_targets(targets: tuple[MemberTarget, ...]) -> list[dict[str, Any]]:
    """Return the target of every member, in the order of the configuration."""
    return [
        {
            "member_id": target.member_id,
            "position": None if target.position is None else target.position.value,
        }
        for target in targets
    ]


@dataclass(frozen=True, slots=True)
class ReasonOutcome:
    """What a reason event says about one decision.

    ``key`` is the outcome without the times that can move from one recompute
    to the next; an event is fired when it changes.
    """

    reason: ReasonCode
    layer: str
    wish_class: str
    wish_reason: ReasonCode
    target: int | None
    gate: str | None
    gate_rule: str | None
    dry_run: bool
    until: str | None

    @property
    def key(self) -> tuple[object, ...]:
        """Return what has to change for a second event."""
        return (
            self.reason,
            self.layer,
            self.wish_reason,
            self.target,
            self.gate,
            self.gate_rule,
            self.dry_run,
        )

    def as_event_data(self) -> dict[str, Any]:
        """Return the part of the event data that describes the outcome."""
        return {
            "reason": self.reason.value,
            "layer": self.layer,
            "wish_class": self.wish_class,
            "wish_reason": self.wish_reason.value,
            "target": self.target,
            "gate": self.gate,
            "gate_rule": self.gate_rule,
            "dry_run": self.dry_run,
            "until": self.until,
        }


@unique
class Unchanged(Enum):
    """The answer of :func:`reason_outcome` for a decision that changes nothing."""

    UNCHANGED = "unchanged"


UNCHANGED: Final = Unchanged.UNCHANGED


def reason_outcome(
    decision: Decision, *, sent: bool, dry_run: bool
) -> ReasonOutcome | Unchanged | None:
    """Return the outcome a reason event reports, ``None``, or :data:`UNCHANGED`.

    An event is due when a layer wants a position and:

    - the command was handed on (``sent``; ``sent`` says the controller really
      gave commands, after its own dry-run check);
    - the dry-run rule recorded what would have been sent (``dry_run``);
    - the gate deferred or suppressed it, with the reason of the rule;
    - a constraint left no target, with the reason of the constraint.

    ``None`` means no movement is wanted, or the target is reached: the
    outcome of the last event is over. :data:`UNCHANGED` means the command is
    still under way (a duplicate): nothing to report and nothing to forget.
    """
    wish = decision.winning_wish
    if wish is None or wish.kind is not WishKind.TARGET:
        return None
    gate = decision.gate
    if gate is None:
        # A target without a gate: a constraint pinned every member.
        pinned = pinning_constraint(decision)
        reason = wish.reason if pinned is None else pinned.reason
    elif gate.reason in _NEUTRAL:
        return UNCHANGED
    elif gate.reason is ReasonCode.TARGET_REACHED:
        return None
    elif gate.kind is GateKind.SEND:
        if not sent:
            return None
        reason = ReasonCode.SENT
    else:
        reason = gate.reason
    return ReasonOutcome(
        reason=reason,
        layer=wish.layer.value,
        wish_class=wish.wish_class.value,
        wish_reason=wish.reason,
        target=(
            common_position(gate.would_send)
            if gate is not None and gate.would_send
            else common_position(decision.targets)
        ),
        gate=None if gate is None else gate.kind.value,
        gate_rule=None if gate is None or gate.rule is None else gate.rule.value,
        dry_run=dry_run,
        until=None if gate is None else _iso(gate.until),
    )


def plain(value: object) -> object:
    """Return a value of a resolved setting or a profile as plain JSON data.

    Enumerations become their value, times and dates ISO text, durations
    whole seconds, positions their number, collections lists or mappings.
    A value of any other type is shown by the name of its type only.
    """
    result: object
    if value is None or isinstance(value, bool | int | float | str):
        result = value
    elif isinstance(value, Enum):
        result = plain(value.value)
    elif isinstance(value, Position):
        result = value.value
    elif hasattr(value, "isoformat"):
        result = value.isoformat()
    elif hasattr(value, "total_seconds"):
        result = value.total_seconds()
    elif isinstance(value, Mapping):
        result = {str(key): plain(item) for key, item in value.items()}
    elif isinstance(value, tuple | list | frozenset | set):
        items = [plain(item) for item in value]
        result = sorted(items, key=str) if isinstance(value, frozenset | set) else items
    elif hasattr(value, "__dataclass_fields__"):
        result = {
            name: plain(getattr(value, name)) for name in value.__dataclass_fields__
        }
    else:
        result = f"<{type(value).__name__}>"
    return result
