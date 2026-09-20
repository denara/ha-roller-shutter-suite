"""What a feature registers with the arbiter: a layer, a constraint, a gate rule.

A registration is data. It names its place (the layer, the constraint or the
gate rule of the model's enumerations, which fix the order), the wish classes
it applies to, and a pure function. Nothing here evaluates anything.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Final

from custom_components.roller_shutter_suite.core.model import (
    GATE_RULE_REASONS,
    Constraint,
    ConstraintResult,
    GateOutcome,
    GateRule,
    Layer,
    MemberTarget,
    OwnCommand,
    Position,
    WindowConfig,
    Wish,
    WishClass,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode

from .controls import EffectiveControls
from .fire_bypass import FIRE_BYPASS

ALL_CLASSES: frozenset[WishClass] = frozenset(WishClass)
"""Fire, protection and comfort."""


_CLASS_RANK: Final = MappingProxyType(
    {WishClass.COMFORT: 0, WishClass.PROTECTION: 1, WishClass.FIRE: 2}
)


def outranks(wish_class: WishClass, other: WishClass) -> bool:
    """Return whether a wish class stands above another: fire, protection, comfort."""
    return _CLASS_RANK[wish_class] > _CLASS_RANK[other]


def reported_positions(snapshot: WorldSnapshot) -> dict[str, Position | None]:
    """Return what every observed member reports as its position, if anything."""
    return {
        member.member_id: member.observation.position
        for member in snapshot.observation.members
    }


type LayerFunction = Callable[[WindowConfig, WorldSnapshot], Wish]
"""A layer: the window configuration and the world snapshot in, a wish out.

The persisted window state is part of the snapshot (``snapshot.state``).
"""


@dataclass(frozen=True, slots=True)
class LayerRegistration:
    """One layer, the function that answers for it, and the function it belongs to.

    ``function`` is the stable identifier of the function of the integration
    the layer belongs to (``schedule``, ``shading``, ``privacy``, ``sleep``,
    ``request`` ...). A comfort layer has to declare it: a window can have a
    function disabled because a stored setting of it is faulty, and the
    arbiter then does not ask the layer. The fire layer and the protection
    layer are never disabled; what they declare is ignored.
    """

    layer: Layer
    evaluate: LayerFunction
    function: str | None = None

    def __post_init__(self) -> None:
        """Validate the place of the registration and the declared function."""
        if not isinstance(self.layer, Layer):
            raise TypeError("a layer is registered for a member of 'Layer'")
        if self.function is not None and (
            not isinstance(self.function, str) or not self.function
        ):
            raise ValueError("the function of a layer is a non-empty identifier")
        if self.can_be_disabled and self.function is None:
            raise ValueError(
                f"the comfort layer {self.layer.value!r} declares the function it "
                "belongs to"
            )

    @property
    def can_be_disabled(self) -> bool:
        """Return whether the layer is a comfort layer; only those can be disabled."""
        return self.layer.wish_class is WishClass.COMFORT


@dataclass(frozen=True, slots=True)
class ConstraintInput:
    """What a constraint sees: the winning wish and the targets so far."""

    config: WindowConfig
    snapshot: WorldSnapshot
    wish: Wish
    targets: tuple[MemberTarget, ...]

    @property
    def current_positions(self) -> dict[str, Position | None]:
        """Return the reported position of every member, if it reports one."""
        return reported_positions(self.snapshot)


type ConstraintFunction = Callable[[ConstraintInput], ConstraintResult | None]
"""A constraint: returns its result, or ``None`` if it has nothing to report."""


type ViolationFunction = Callable[[ConstraintInput], bool]
"""Says whether the position a window has right now violates a constraint."""


@dataclass(frozen=True, slots=True)
class ConstraintRegistration:
    """One constraint, the wish classes it applies to, and its function.

    ``violated_by_position`` is for a constraint that says where a window may
    *stand* (a floor, for example), as opposed to one that says which
    *movements* are allowed. It answers whether a member stands on the wrong
    side right now. A movement that restores such a constraint is exempt from
    the minimum change of motor protection, however small it is. A constraint
    about movements leaves it out.
    """

    constraint: Constraint
    applies_to: frozenset[WishClass]
    apply: ConstraintFunction
    violated_by_position: ViolationFunction | None = None

    def __post_init__(self) -> None:
        """Refuse a constraint on fire: fire is subject to no constraint at all."""
        if not isinstance(self.constraint, Constraint):
            raise TypeError("a constraint is registered for a member of 'Constraint'")
        object.__setattr__(self, "applies_to", frozenset(self.applies_to))
        if not self.applies_to:
            raise ValueError("a constraint names the wish classes it applies to")
        if WishClass.FIRE in self.applies_to:
            raise ValueError("fire is subject to no constraint at all")


@dataclass(frozen=True, slots=True)
class GateInput:
    """What a gate rule sees.

    - ``to_send``: the targets that reached the gate (pinned members left out).
    - ``restores_constraint``: whether a constraint that applies to the wish
      is violated by the position the window has right now, so that the
      movement restores it.
    - ``controls``: the effective pause, lock, mode and dry-run of the window.
    - ``own_commands`` and ``last_comfort_movement``: the own commands per
      member and the motor protection clock **as this window has to judge
      them**. For an armed window they are the real ones. For a window in
      dry-run they are the simulated ones, and never the real ones. A rule
      that depends on own commands reads them here and not from
      ``snapshot.state``; that is what keeps the real and the simulated state
      apart.
    """

    config: WindowConfig
    snapshot: WorldSnapshot
    wish: Wish
    to_send: tuple[MemberTarget, ...]
    controls: EffectiveControls
    own_commands: Mapping[str, OwnCommand]
    last_comfort_movement: datetime | None
    restores_constraint: bool = False

    def __post_init__(self) -> None:
        """Copy and freeze the commands."""
        object.__setattr__(
            self, "own_commands", MappingProxyType(dict(self.own_commands))
        )

    @property
    def current_positions(self) -> dict[str, Position | None]:
        """Return the reported position of every member, if it reports one."""
        return reported_positions(self.snapshot)


type GateFunction = Callable[[GateInput], GateOutcome | None]
"""A gate rule: returns its outcome, or ``None`` if it does not apply."""


@dataclass(frozen=True, slots=True)
class GateRuleRegistration:
    """One gate rule, the wish classes it can hold back, and its function.

    ``reasons`` are the reason codes this registration can give. By default
    they are all reasons of the rule. A rule whose parts apply to different
    wish classes is registered once per part, each with its own reasons (the
    rule "movement in flight" is); the parts must not depend on the order in
    which they are asked.
    """

    rule: GateRule
    applies_to: frozenset[WishClass]
    evaluate: GateFunction
    reasons: frozenset[ReasonCode] = frozenset()

    def __post_init__(self) -> None:
        """Keep the fire bypass exact in both directions."""
        if not isinstance(self.rule, GateRule):
            raise TypeError("a gate rule is registered for a member of 'GateRule'")
        object.__setattr__(self, "applies_to", frozenset(self.applies_to))
        if not self.applies_to:
            raise ValueError("a gate rule names the wish classes it applies to")
        reasons = frozenset(self.reasons) or GATE_RULE_REASONS[self.rule]
        object.__setattr__(self, "reasons", reasons)
        if not reasons <= GATE_RULE_REASONS[self.rule]:
            raise ValueError(
                f"the gate rule {self.rule.value!r} gives only its own reasons"
            )
        if reasons <= FIRE_BYPASS:
            if WishClass.FIRE in self.applies_to:
                raise ValueError(
                    f"the gate rule {self.rule.value!r} is part of the fire bypass "
                    "and cannot hold back fire"
                )
        elif reasons & FIRE_BYPASS:
            raise ValueError(
                f"the gate rule {self.rule.value!r} mixes reasons that fire skips "
                "with reasons that it does not; register the parts separately"
            )
        elif self.applies_to != ALL_CLASSES:
            raise ValueError(
                f"the gate rule {self.rule.value!r} is never skipped and applies "
                "to every wish class"
            )
