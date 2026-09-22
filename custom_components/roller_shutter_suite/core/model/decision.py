"""Wish, constraint result, gate outcome and the decision that carries them.

Reason codes are tied to their group (``ReasonCategory`` of the module ``reasons``):

- a wish and a layer reason take codes of the groups "winning or contributing
  layers" and "why a layer did not act"; a wish for a target only the former;
- a constraint result takes codes of the group "constraints", and only those
  that belong to its constraint;
- a gate outcome takes codes of the group "gate" plus ``capability_missing``
  (gate rule 2 suppresses "with the capability reason"), and only those that
  belong to its rule;
- codes of the group "events only" never appear inside a decision.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum, unique
from types import MappingProxyType
from typing import Final, Self

from custom_components.roller_shutter_suite.core.reasons import (
    ReasonCategory,
    ReasonCode,
)

from ._validation import (
    require_aware_or_none,
    require_finite,
    require_identifier,
    require_optional_type,
    require_type,
    require_unique,
)
from .functions import FunctionId
from .values import Position


def _require_reason(
    reason: ReasonCode, allowed: tuple[ReasonCategory, ...], what: str
) -> None:
    require_type(reason, ReasonCode, what)
    if reason.category not in allowed:
        groups = " or ".join(repr(category.value) for category in allowed)
        raise ValueError(
            f"{what} must be a code of the group {groups}; {reason.value!r} "
            f"belongs to {reason.category.value!r}"
        )


_LAYER_GROUPS: Final = (ReasonCategory.LAYER, ReasonCategory.LAYER_INACTIVE)


# ---------------------------------------------------------------------------
# Wishes
# ---------------------------------------------------------------------------


@unique
class WishClass(StrEnum):
    """The class of a wish; constraints and gate rules apply per class."""

    FIRE = "fire"
    PROTECTION = "protection"
    COMFORT = "comfort"


@unique
class Layer(StrEnum):
    """The layers of the arbiter, in the order in which they are evaluated."""

    FIRE = "fire"
    PROTECTION = "protection"
    SLEEP = "sleep"
    EXTERNAL_REQUEST = "external_request"
    PRIVACY = "privacy"
    SHADING = "shading"
    """Shading and solar heating; the two exclude each other."""
    SCHEDULE = "schedule"

    @property
    def wish_class(self) -> WishClass:
        """Return the class of the wishes of this layer.

        The one exception is a property of the wish, not of the layer: see
        ``Wish.wish_class``.
        """
        if self is Layer.FIRE:
            return WishClass.FIRE
        if self is Layer.PROTECTION:
            return WishClass.PROTECTION
        return WishClass.COMFORT


@unique
class WishKind(StrEnum):
    """What a layer answers."""

    TARGET = "target"
    """The layer wants a position."""
    LEAVE_ALONE = "leave_alone"
    """The layer wins and holds the window where it is."""
    NO_OPINION = "no_opinion"
    """The layer steps aside; the next layer is asked."""


@unique
class Direction(StrEnum):
    """A limit that a wish carries itself (constraint 1)."""

    RAISE_ONLY = "raise_only"
    LOWER_ONLY = "lower_only"


@dataclass(frozen=True, slots=True)
class MemberTarget:
    """The target of one member; ``None`` means the member stays where it is.

    The position is on the motor scale: it is what the member is commanded to
    and what it reports. The glass calibration of shading is applied before,
    by the shading layer, and never enters a target.
    """

    member_id: str
    position: Position | None

    def __post_init__(self) -> None:
        """Validate the member identifier."""
        require_identifier(self.member_id, "the member of a target")
        if self.position is not None:
            require_type(self.position, Position, "the position of a target")


def _require_member_targets(
    targets: tuple[MemberTarget, ...], what: str, *, positions_required: bool
) -> None:
    for target in targets:
        require_type(target, MemberTarget, what)
        if positions_required and target.position is None:
            raise ValueError(f"{what} must state a position for every member")
    require_unique((target.member_id for target in targets), f"the members of {what}")


def _member_ids(targets: tuple[MemberTarget, ...]) -> tuple[str, ...]:
    return tuple(target.member_id for target in targets)


@dataclass(frozen=True, slots=True)
class Wish:
    """The answer of one layer: a target position, leave alone, or no opinion.

    A wish for a target states it in one of two ways, never both:

    - ``position``: one position for all members of the window;
    - ``member_positions``: one position per member, on the motor scale (the
      glass calibration has been applied by the shading layer already). A
      layer that decides per member (shading, decision 9) also states the
      quantity it decided in as ``ray_height`` (metres above the floor).

    ``triggered_at`` is the time of the trigger of a wish for a target: the
    moment from which the layer wants what it wants now. A boundary of the
    schedule fired, sleep mode or privacy was switched, an external request
    arrived, a shading or solar heating episode began. It stays the same
    while the layer only tracks (a new shading position inside an episode),
    and it stays the old one when the wish wins again because a higher layer
    dropped out. Motor protection reads it: a wish whose trigger lies after
    the last own comfort movement is fresh. A wish that states no trigger is
    never fresh.
    """

    layer: Layer
    kind: WishKind
    reason: ReasonCode
    position: Position | None = None
    direction: Direction | None = None
    member_positions: tuple[MemberTarget, ...] = ()
    ray_height: float | None = None
    triggered_at: datetime | None = None

    def __post_init__(self) -> None:
        """Reject combinations that do not describe one of the three answers."""
        require_type(self.layer, Layer, "the layer of a wish")
        require_type(self.kind, WishKind, "the kind of a wish")
        if (
            self.reason is ReasonCode.PROTECTION_RETURN_MANUAL
            and self.layer is not Layer.PROTECTION
        ):
            raise ValueError(
                "the reason 'protection_return_manual' belongs to a wish of the "
                "protection layer"
            )
        object.__setattr__(self, "member_positions", tuple(self.member_positions))
        if self.kind is WishKind.TARGET:
            _require_reason(
                self.reason,
                (ReasonCategory.LAYER,),
                "the reason of a wish for a target",
            )
            self._validate_target()
            return
        _require_reason(self.reason, _LAYER_GROUPS, "the reason of a wish")
        if (
            self.position is not None
            or self.direction is not None
            or self.member_positions
            or self.ray_height is not None
            or self.triggered_at is not None
        ):
            raise ValueError(
                f"a wish of the kind {self.kind.value!r} carries no position, "
                "direction, member positions, ray height or trigger time"
            )

    def _validate_target(self) -> None:
        if (self.position is None) == (not self.member_positions):
            raise ValueError(
                "a wish of the kind 'target' needs either one position for all "
                "members or one position per member"
            )
        if self.position is not None:
            require_type(self.position, Position, "the position of a wish")
        if self.direction is not None:
            require_type(self.direction, Direction, "the direction of a wish")
        _require_member_targets(
            self.member_positions,
            "the member positions of a wish",
            positions_required=True,
        )
        if self.ray_height is not None:
            require_finite(self.ray_height, "the ray height of a wish")
        require_aware_or_none(self.triggered_at, "the trigger time of a wish")

    @classmethod
    def target(
        cls,
        layer: Layer,
        reason: ReasonCode,
        position: Position,
        *,
        direction: Direction | None = None,
        ray_height: float | None = None,
    ) -> Self:
        """Return a wish for one target position for all members."""
        return cls(
            layer=layer,
            kind=WishKind.TARGET,
            reason=reason,
            position=position,
            direction=direction,
            ray_height=ray_height,
        )

    @classmethod
    def target_per_member(
        cls,
        layer: Layer,
        reason: ReasonCode,
        member_positions: Iterable[MemberTarget],
        *,
        direction: Direction | None = None,
        ray_height: float | None = None,
    ) -> Self:
        """Return a wish for one target position per member."""
        return cls(
            layer=layer,
            kind=WishKind.TARGET,
            reason=reason,
            direction=direction,
            member_positions=tuple(member_positions),
            ray_height=ray_height,
        )

    def triggered(self, at: datetime) -> Self:
        """Return the same wish for a target with the time of its trigger."""
        return replace(self, triggered_at=at)

    @classmethod
    def leave_alone(cls, layer: Layer, reason: ReasonCode) -> Self:
        """Return a wish that wins and holds the window where it is."""
        return cls(layer=layer, kind=WishKind.LEAVE_ALONE, reason=reason)

    @classmethod
    def no_opinion(cls, layer: Layer, reason: ReasonCode) -> Self:
        """Return the answer of a layer that steps aside, with the reason why."""
        return cls(layer=layer, kind=WishKind.NO_OPINION, reason=reason)

    @property
    def wish_class(self) -> WishClass:
        """Return the class of the wish, which follows from its layer.

        There is one exception (decision 14): the return to the manual position
        after a protection event, reason ``protection_return_manual``, is a
        wish of class comfort from the protection layer. That reason is
        accepted on a wish of the protection layer only, so the class still
        cannot contradict layer and reason.
        """
        if self.reason is ReasonCode.PROTECTION_RETURN_MANUAL:
            return WishClass.COMFORT
        return self.layer.wish_class


@dataclass(frozen=True, slots=True)
class LayerReason:
    """Why one layer, or one part of a layer, did not win a recompute.

    ``function`` is the function of the integration that spoke: the one the
    registration of the layer, or of the part of the layer, declares. The
    arbiter fills it from the registration, never the layer itself, so a
    reader of the record does not need the registry. It is ``None`` for a
    registration that declares no function and for a layer nobody registered.
    """

    layer: Layer
    reason: ReasonCode
    function: FunctionId | None = None

    def __post_init__(self) -> None:
        """Validate the types, so a reason is never free text."""
        require_type(self.layer, Layer, "the layer of a layer reason")
        _require_reason(self.reason, _LAYER_GROUPS, "the reason of a layer reason")
        require_optional_type(
            self.function, FunctionId, "the function of a layer reason"
        )


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------


@unique
class Constraint(StrEnum):
    """The constraints of the arbiter, in the order in which they are applied."""

    DIRECTION = "direction"
    SLEEP_ROOM_EXCEPTION = "sleep_room_exception"
    LOCKOUT_PROTECTION = "lockout_protection"
    VENTILATION_FLOOR = "ventilation_floor"
    RAIN_WHILE_VENTILATING = "rain_while_ventilating"
    FROST_PROTECTION = "frost_protection"
    NO_INTERMEDIATE_POSITION = "no_intermediate_position"


CONSTRAINT_REASONS: Final = MappingProxyType(
    {
        Constraint.DIRECTION: frozenset({ReasonCode.ONLY_RAISE, ReasonCode.ONLY_LOWER}),
        Constraint.SLEEP_ROOM_EXCEPTION: frozenset(
            {ReasonCode.SLEEP_EXCEPTION_NO_OPEN}
        ),
        Constraint.LOCKOUT_PROTECTION: frozenset(
            {
                ReasonCode.LOCKOUT_DOOR_OPEN,
                ReasonCode.LOCKOUT_VOID_TAMPER,
                ReasonCode.LOCKOUT_CONTACT_UNAVAILABLE,
            }
        ),
        Constraint.VENTILATION_FLOOR: frozenset({ReasonCode.VENTILATION_FLOOR}),
        Constraint.RAIN_WHILE_VENTILATING: frozenset(
            {ReasonCode.RAIN_VENTILATION_FLOOR}
        ),
        Constraint.FROST_PROTECTION: frozenset(
            {
                ReasonCode.FROST_LIMIT,
                ReasonCode.FROST_LIMIT_SOURCE_BLIND,
                ReasonCode.FROST_HOLD,
            }
        ),
        Constraint.NO_INTERMEDIATE_POSITION: frozenset(
            {ReasonCode.NO_INTERMEDIATE_POSITION}
        ),
    }
)
"""The reason codes each constraint can report (sections 2.2 and 5)."""


@dataclass(frozen=True, slots=True)
class ConstraintResult:
    """What one constraint did to the winning wish.

    ``targets`` lists every member of the window with its target after this
    constraint, on the motor scale. A member whose position is ``None`` was
    pinned: it stays where it is. A constraint that reports without changing
    anything (lockout protection that is void because of the tamper contact)
    repeats the targets it received.

    ``constraint_failed`` is the one reason every constraint can carry. The
    arbiter writes it, never a constraint itself: the constraint raised an
    exception, and ``targets`` are its cautious result.
    """

    constraint: Constraint
    reason: ReasonCode
    targets: tuple[MemberTarget, ...]

    def __post_init__(self) -> None:
        """Validate the types, the pairing of constraint and reason, the targets."""
        require_type(self.constraint, Constraint, "the constraint of a result")
        _require_reason(
            self.reason,
            (ReasonCategory.CONSTRAINT,),
            "the reason of a constraint result",
        )
        if (
            self.reason is not ReasonCode.CONSTRAINT_FAILED
            and self.reason not in CONSTRAINT_REASONS[self.constraint]
        ):
            raise ValueError(
                f"the constraint {self.constraint.value!r} does not report the "
                f"reason {self.reason.value!r}"
            )
        object.__setattr__(self, "targets", tuple(self.targets))
        if not self.targets:
            raise ValueError("a constraint result lists the target of every member")
        _require_member_targets(
            self.targets, "the targets of a constraint result", positions_required=False
        )


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


@unique
class GateRule(StrEnum):
    """The rules of the gate, in the order in which they are evaluated."""

    MAINTENANCE_LOCK = "maintenance_lock"
    NO_MEMBER_CAN_EXECUTE = "no_member_can_execute"
    TARGET_REACHED = "target_reached"
    OPERATING_MODE = "operating_mode"
    PAUSE = "pause"
    PERSON_AT_WINDOW_DAM = "person_at_window_dam"
    MANUAL_OVERRIDE_DAM = "manual_override_dam"
    MOVEMENT_IN_FLIGHT = "movement_in_flight"
    MOTOR_PROTECTION = "motor_protection"
    COMMAND_BACKOFF = "command_backoff"
    STAGGERING = "staggering"
    DRY_RUN = "dry_run"


GATE_RULE_REASONS: Final = MappingProxyType(
    {
        GateRule.MAINTENANCE_LOCK: frozenset({ReasonCode.MAINTENANCE_LOCK}),
        GateRule.NO_MEMBER_CAN_EXECUTE: frozenset(
            {ReasonCode.COVER_UNAVAILABLE, ReasonCode.CAPABILITY_MISSING}
        ),
        GateRule.TARGET_REACHED: frozenset({ReasonCode.TARGET_REACHED}),
        GateRule.OPERATING_MODE: frozenset(
            {ReasonCode.MODE_OFF, ReasonCode.MODE_PROTECTION_ONLY}
        ),
        GateRule.PAUSE: frozenset({ReasonCode.PAUSED}),
        GateRule.PERSON_AT_WINDOW_DAM: frozenset({ReasonCode.PERSON_AT_WINDOW}),
        GateRule.MANUAL_OVERRIDE_DAM: frozenset({ReasonCode.MANUAL_OVERRIDE}),
        GateRule.MOVEMENT_IN_FLIGHT: frozenset(
            {
                ReasonCode.MOVEMENT_IN_FLIGHT,
                ReasonCode.DUPLICATE_COMMAND,
                ReasonCode.MOVEMENT_TAKEN_OVER,
            }
        ),
        GateRule.MOTOR_PROTECTION: frozenset(
            {
                ReasonCode.MIN_CHANGE,
                ReasonCode.MIN_INTERVAL,
                ReasonCode.TRIGGER_TIME_MISSING,
            }
        ),
        GateRule.COMMAND_BACKOFF: frozenset({ReasonCode.COMMAND_BACKOFF}),
        GateRule.STAGGERING: frozenset({ReasonCode.STAGGERED}),
        GateRule.DRY_RUN: frozenset({ReasonCode.DRY_RUN}),
    }
)
"""The reason codes each gate rule can give (sections 2.3 and 5)."""


@unique
class GateKind(StrEnum):
    """The three outcomes of the gate."""

    SEND = "send"
    DEFER = "defer"
    SUPPRESS = "suppress"


@dataclass(frozen=True, slots=True)
class GateOutcome:
    """The answer of the gate: send, defer until, or suppress, with a reason.

    ``rule`` is the gate rule that decided; it is ``None`` only for "send",
    where no rule applied.

    A deferral states exactly one of two times:

    - ``until``: the point in time at which the deferral ends, if it is known;
    - ``reevaluate_no_later_than``: if the deferral ends with a condition whose
      time is not known (a member becomes available, the members come to
      rest), the latest time at which the window is recomputed from the state
      it has then. It is an upper bound, not an expected end, and nothing is
      replayed. A deferral without either is refused: nothing waits forever.

    For a window in dry-run, ``dry_run`` is true and the outcome is the
    hypothetical one: either the rule ``dry_run`` decided and ``would_send``
    lists the command that would have been sent, or ``rule`` names the earlier
    rule that would have held the wish back.

    ``gate_rule_failed`` is the one reason every rule can carry. The arbiter
    writes it, never a rule itself: the rule raised an exception and holds
    the wish back. A dry-run rule that failed records no would-be command.
    """

    kind: GateKind
    reason: ReasonCode
    rule: GateRule | None = None
    until: datetime | None = None
    reevaluate_no_later_than: datetime | None = None
    dry_run: bool = False
    would_send: tuple[MemberTarget, ...] = ()

    def __post_init__(self) -> None:
        """Reject outcomes that contradict themselves."""
        require_type(self.kind, GateKind, "the kind of a gate outcome")
        require_type(self.reason, ReasonCode, "the reason of a gate outcome")
        if (
            self.reason.category is not ReasonCategory.GATE
            and self.reason is not ReasonCode.CAPABILITY_MISSING
        ):
            raise ValueError(
                "the reason of a gate outcome must be a code of the group 'gate' "
                f"or 'capability_missing'; {self.reason.value!r} belongs to "
                f"{self.reason.category.value!r}"
            )
        require_type(self.dry_run, bool, "the dry-run flag of a gate outcome")
        require_aware_or_none(self.until, "the end of a deferral")
        require_aware_or_none(
            self.reevaluate_no_later_than, "the latest re-evaluation of a deferral"
        )
        object.__setattr__(self, "would_send", tuple(self.would_send))
        _require_member_targets(
            self.would_send, "the would-be command", positions_required=True
        )
        if self.kind is not GateKind.DEFER and (
            self.until is not None or self.reevaluate_no_later_than is not None
        ):
            raise ValueError("only a deferral has an end or a latest re-evaluation")
        if self.kind is GateKind.SEND:
            self._validate_send()
        else:
            self._validate_held_back()

    def _validate_send(self) -> None:
        if self.reason is not ReasonCode.SENT:
            raise ValueError("the outcome 'send' has the reason 'sent'")
        if self.rule is not None:
            raise ValueError("the outcome 'send' means that no gate rule applied")
        if self.would_send:
            raise ValueError("the outcome 'send' has no would-be command")
        if self.dry_run:
            raise ValueError("a window in dry-run never sends")

    def _validate_held_back(self) -> None:
        if self.reason is ReasonCode.SENT:
            raise ValueError("only the outcome 'send' has the reason 'sent'")
        if self.rule is None:
            raise ValueError("a deferral or a suppression names the rule that decided")
        require_type(self.rule, GateRule, "the rule of a gate outcome")
        failed = self.reason is ReasonCode.GATE_RULE_FAILED
        if not failed and self.reason not in GATE_RULE_REASONS[self.rule]:
            raise ValueError(
                f"the gate rule {self.rule.value!r} does not give the reason "
                f"{self.reason.value!r}"
            )
        if self.kind is GateKind.DEFER and (self.until is None) == (
            self.reevaluate_no_later_than is None
        ):
            raise ValueError(
                "a deferral states either the time at which it ends or, if that "
                "is not known, the latest time of the re-evaluation"
            )
        # A dry-run rule that failed recorded nothing: it holds the wish back
        # like every failed rule, without a would-be command.
        by_dry_run_rule = self.rule is GateRule.DRY_RUN and not failed
        if by_dry_run_rule != bool(self.would_send):
            raise ValueError(
                "the rule 'dry_run', and only it, records the would-be command"
            )
        if by_dry_run_rule and not (self.dry_run and self.kind is GateKind.SUPPRESS):
            raise ValueError("the rule 'dry_run' suppresses, for a window in dry-run")

    @classmethod
    def send(cls) -> Self:
        """Return the outcome "send"."""
        return cls(kind=GateKind.SEND, reason=ReasonCode.SENT)

    @classmethod
    def defer(
        cls,
        rule: GateRule,
        reason: ReasonCode,
        until: datetime | None = None,
        *,
        reevaluate_no_later_than: datetime | None = None,
        dry_run: bool = False,
    ) -> Self:
        """Return the outcome "defer": until a known time, or with an upper bound."""
        return cls(
            kind=GateKind.DEFER,
            reason=reason,
            rule=rule,
            until=until,
            reevaluate_no_later_than=reevaluate_no_later_than,
            dry_run=dry_run,
        )

    @classmethod
    def suppress(
        cls, rule: GateRule, reason: ReasonCode, *, dry_run: bool = False
    ) -> Self:
        """Return the outcome "suppress"."""
        return cls(kind=GateKind.SUPPRESS, reason=reason, rule=rule, dry_run=dry_run)

    @classmethod
    def would_have_sent(cls, targets: Iterable[MemberTarget]) -> Self:
        """Return the outcome of the dry-run rule with the would-be command."""
        return cls(
            kind=GateKind.SUPPRESS,
            reason=ReasonCode.DRY_RUN,
            rule=GateRule.DRY_RUN,
            dry_run=True,
            would_send=tuple(targets),
        )


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


@unique
class EvaluationStage(StrEnum):
    """The stage of a recompute in which a registered function raised."""

    LAYER = "layer"
    CONSTRAINT = "constraint"
    GATE_RULE = "gate_rule"


_PLACE_OF_STAGE: Final = MappingProxyType(
    {
        EvaluationStage.LAYER: Layer,
        EvaluationStage.CONSTRAINT: Constraint,
        EvaluationStage.GATE_RULE: GateRule,
    }
)


@dataclass(frozen=True, slots=True)
class EvaluationFault:
    """A layer, a constraint or a gate rule raised an exception during a recompute.

    A fact for the caller, which logs it and may raise a repair issue; the
    core does not log. The decision itself already carries the consequence,
    with a reason code: the layer had no opinion (``layer_failed``), the
    constraint applied its cautious result (``constraint_failed``), the gate
    rule held the wish back (``gate_rule_failed``).

    - ``stage`` and ``place``: where it happened; ``place`` is the member of
      ``Layer``, ``Constraint`` or ``GateRule`` that belongs to the stage.
    - ``function``: the function the registration declares, if any. For a
      layer that is registered in parts it tells the parts apart.
    - ``error``: the name of the exception class, an identifier and no text.
    - ``exception``: the exception itself, for the log of the caller. It takes
      no part in comparing two faults, so the same snapshot still gives an
      equal decision.
    """

    stage: EvaluationStage
    place: Layer | Constraint | GateRule
    error: str
    function: FunctionId | None = None
    exception: Exception | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        """Validate that the place belongs to the stage."""
        require_type(self.stage, EvaluationStage, "the stage of an evaluation fault")
        require_type(
            self.place,
            _PLACE_OF_STAGE[self.stage],
            f"the place of a fault in the stage {self.stage.value!r}",
        )
        require_identifier(self.error, "the error of an evaluation fault")
        require_optional_type(
            self.function, FunctionId, "the function of an evaluation fault"
        )
        require_optional_type(
            self.exception, Exception, "the exception of an evaluation fault"
        )

    @classmethod
    def of(
        cls,
        place: Layer | Constraint | GateRule,
        function: FunctionId | None,
        exception: Exception,
    ) -> Self:
        """Return the fault for an exception that was raised at the place."""
        stage = next(
            stage for stage, kind in _PLACE_OF_STAGE.items() if isinstance(place, kind)
        )
        return cls(stage, place, type(exception).__name__, function, exception)


@dataclass(frozen=True, slots=True)
class Decision:
    """The complete result of one recompute.

    - ``winning_wish``: the wish of the first layer with an opinion; ``None``
      if no layer had one (a window without a configured schedule).
    - ``winning_function``: the function of the registration whose wish won,
      written by the arbiter from that registration; ``None`` if nothing won
      or the registration declares no function.
    - ``other_layers``: for every other layer the reason why it did not win,
      each with the function that spoke. A layer that is registered in parts
      (one per function) has one entry per part that did not win, so entries
      are unique per layer and function. The winning layer appears here only
      through its other parts: with a function, and not the winner's. A part
      whose function is disabled for the window by a faulty stored setting
      was not asked and says ``function_disabled_by_fault``.
    - ``constraints``: the results of the constraints that applied, in order.
    - ``targets``: the target of every member after the constraints, on the
      motor scale. Empty if the winning wish is not a target. A member with
      the position ``None`` was pinned by a constraint.
    - ``gate``: the outcome of the gate; ``None`` if nothing reached the gate,
      because there is no target or a constraint pinned every member.
    - ``faults``: the layers, constraints and gate rules that raised an
      exception during this recompute, in the order in which they were
      evaluated; empty in a sound installation. The parts above already carry
      what each fault led to (``layer_failed``, ``constraint_failed``,
      ``gate_rule_failed``); this is the fact for the caller, who logs it.
      Two faults have no entry of their own above: an exception in the check
      whether the current position violates a constraint (no exemption from
      the minimum change is granted then), and a dry-run rule that failed
      with a fire wish pending (the command is sent).

    The member positions of the wish, the targets of every constraint result
    and ``targets`` name the same members in the same order.
    """

    winning_wish: Wish | None
    other_layers: tuple[LayerReason, ...] = ()
    constraints: tuple[ConstraintResult, ...] = ()
    targets: tuple[MemberTarget, ...] = ()
    gate: GateOutcome | None = None
    winning_function: FunctionId | None = None
    faults: tuple[EvaluationFault, ...] = ()

    def __post_init__(self) -> None:
        """Reject records whose parts contradict each other."""
        object.__setattr__(self, "other_layers", tuple(self.other_layers))
        object.__setattr__(self, "constraints", tuple(self.constraints))
        object.__setattr__(self, "targets", tuple(self.targets))
        object.__setattr__(self, "faults", tuple(self.faults))
        for fault in self.faults:
            require_type(fault, EvaluationFault, "a fault of a decision")
        self._validate_layers()
        for result in self.constraints:
            require_type(result, ConstraintResult, "a constraint of a decision")
        _require_member_targets(
            self.targets, "the targets of a decision", positions_required=False
        )
        has_target_wish = (
            self.winning_wish is not None and self.winning_wish.kind is WishKind.TARGET
        )
        if has_target_wish != bool(self.targets):
            raise ValueError(
                "a decision lists the members' targets if, and only if, the "
                "winning wish is a target"
            )
        if not has_target_wish and self.constraints:
            raise ValueError("constraints apply to a target only")
        self._validate_members()
        self._validate_gate()

    def _validate_layers(self) -> None:
        if self.winning_wish is not None:
            require_type(self.winning_wish, Wish, "the winning wish")
            if self.winning_wish.kind is WishKind.NO_OPINION:
                raise ValueError("a wish without an opinion cannot win")
        require_optional_type(
            self.winning_function, FunctionId, "the winning function of a decision"
        )
        if self.winning_function is not None and self.winning_wish is None:
            raise ValueError("without a winning wish there is no winning function")
        seen: set[tuple[Layer, FunctionId | None]] = set()
        for entry in self.other_layers:
            require_type(entry, LayerReason, "a layer reason of a decision")
            if (entry.layer, entry.function) in seen:
                raise ValueError(f"the layer {entry.layer.value!r} is listed twice")
            seen.add((entry.layer, entry.function))
            if self.winning_wish is None or entry.layer is not self.winning_wish.layer:
                continue
            if entry.function is None or entry.function is self.winning_function:
                raise ValueError(
                    "the winning layer is one of the other layers only through "
                    "another part of it: an entry with a function that is not the "
                    "winner's"
                )

    def _validate_members(self) -> None:
        members = _member_ids(self.targets)
        for result in self.constraints:
            if _member_ids(result.targets) != members:
                raise ValueError(
                    "every constraint result names the same members as the "
                    "targets of the decision, in the same order"
                )
        if (
            self.winning_wish is not None
            and self.winning_wish.member_positions
            and _member_ids(self.winning_wish.member_positions) != members
        ):
            raise ValueError(
                "the member positions of the winning wish name the same members "
                "as the targets of the decision, in the same order"
            )

    def _validate_gate(self) -> None:
        to_send = tuple(
            target for target in self.targets if target.position is not None
        )
        if self.gate is None:
            if to_send:
                raise ValueError("a target that is not pinned reaches the gate")
            return
        require_type(self.gate, GateOutcome, "the gate outcome of a decision")
        if not to_send:
            raise ValueError("nothing reaches the gate without a target to send")
        if self.gate.would_send and self.gate.would_send != to_send:
            raise ValueError("the would-be command consists of the decision's targets")

    @property
    def target(self) -> Position | None:
        """Return the target the window shows: the common target of its members.

        If the members have different targets, or one of them is pinned, the
        window shows no target (``None``); ``targets`` has the detail.
        """
        positions = {target.position for target in self.targets}
        if len(positions) != 1:
            return None
        return next(iter(positions))
