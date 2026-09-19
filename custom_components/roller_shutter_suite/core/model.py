"""Data types of the domain core: the vocabulary of ``docs/architecture.md``.

This module holds types only. There is no arbiter, no schedule, no tracker
logic and no geometry here; the blocks that build them exchange the types
defined below. Every type is immutable, validates itself on construction and
compares by value.

Conventions that hold for the whole module:

- A position is an integer from 0 to 100; 100 is fully open, 0 fully closed.
- Every datetime is timezone-aware. A naive datetime is rejected.
- A member is identified by a string that the core treats as opaque.
- The order of the members of a window matters: the first member provides the
  position and the target that the window shows.
- Nothing converts "unknown" or "unavailable" into a number or a boolean.
"""

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum, unique
from types import MappingProxyType
from typing import Final, NoReturn, Self

from .reasons import ReasonCode

# ---------------------------------------------------------------------------
# Plain data for persistence
# ---------------------------------------------------------------------------

type JsonValue = (
    bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
)
"""Plain data that a JSON encoder accepts without any help."""

type JsonObject = dict[str, JsonValue]
"""A JSON object: what the storage port stores for one window."""

WINDOW_STATE_SCHEMA_VERSION: Final = 1
"""Version of the plain data layout written by :meth:`WindowState.to_data`."""

_MAX_POSITION: Final = 100
_MAX_LATCHED_DAY_TYPES: Final = 2
_FULL_CIRCLE: Final = 360.0
_ZENITH: Final = 90.0


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_type(value: object, expected: type, what: str) -> None:
    if not isinstance(value, expected):
        raise TypeError(
            f"{what} must be of type {expected.__name__}, not {type(value).__name__}"
        )


def _require_aware(value: datetime, what: str) -> None:
    _require_type(value, datetime, what)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{what} must be timezone-aware, got a naive datetime")


def _require_aware_or_none(value: datetime | None, what: str) -> None:
    if value is not None:
        _require_aware(value, what)


def _require_identifier(value: str, what: str) -> None:
    _require_type(value, str, what)
    if not value:
        raise ValueError(f"{what} must not be empty")


def _require_unique(identifiers: Iterable[str], what: str) -> None:
    seen: set[str] = set()
    for identifier in identifiers:
        if identifier in seen:
            raise ValueError(f"{what} must be unique, {identifier!r} occurs twice")
        seen.add(identifier)


def _require_finite(value: float, what: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{what} must be a number, not {type(value).__name__}")
    if not math.isfinite(value):
        raise ValueError(f"{what} must be a finite number")


# ---------------------------------------------------------------------------
# Helpers for reading plain data
# ---------------------------------------------------------------------------


def _as_object(value: JsonValue) -> JsonObject:
    if not isinstance(value, dict):
        raise ValueError("expected an object")  # noqa: TRY004
    return value


def _as_list(value: JsonValue) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ValueError("expected a list")  # noqa: TRY004
    return value


def _as_str(value: JsonValue) -> str:
    if not isinstance(value, str):
        raise ValueError("expected a string")  # noqa: TRY004
    return value


def _as_bool(value: JsonValue) -> bool:
    if not isinstance(value, bool):
        raise ValueError("expected true or false")  # noqa: TRY004
    return value


def _as_int(value: JsonValue) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expected an integer")  # noqa: TRY004
    return value


def _as_datetime(value: JsonValue) -> datetime:
    parsed = datetime.fromisoformat(_as_str(value))
    _require_aware(parsed, "a persisted timestamp")
    return parsed


def _as_date(value: JsonValue) -> date:
    return date.fromisoformat(_as_str(value))


def _as_enum[E: StrEnum](enum: type[E]) -> Callable[[JsonValue], E]:
    def convert_enum(value: JsonValue) -> E:
        return enum(_as_str(value))

    return convert_enum


def _optional[T](convert: Callable[[JsonValue], T]) -> Callable[[JsonValue], T | None]:
    def convert_optional(value: JsonValue) -> T | None:
        return None if value is None else convert(value)

    return convert_optional


def _tuple_of[T](
    convert: Callable[[JsonValue], T],
) -> Callable[[JsonValue], tuple[T, ...]]:
    def convert_list(value: JsonValue) -> tuple[T, ...]:
        return tuple(convert(item) for item in _as_list(value))

    return convert_list


def _get[T](data: JsonObject, key: str, convert: Callable[[JsonValue], T]) -> T:
    """Read one key of persisted data; errors name the key they concern."""
    if key not in data:
        raise ValueError(f"the key {key!r} is missing")
    try:
        return convert(data[key])
    except ValueError as err:
        raise ValueError(f"{key}: {err}") from err


def _datetime_data(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, order=True)
class Position:
    """A position of a curtain: 100 is fully open, 0 is fully closed."""

    value: int

    def __post_init__(self) -> None:
        """Reject everything that is not an integer from 0 to 100."""
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise TypeError(
                f"a position must be an integer, not {type(self.value).__name__}"
            )
        if not 0 <= self.value <= _MAX_POSITION:
            raise ValueError(f"a position must be within 0 and 100, got {self.value}")


FULLY_OPEN: Final = Position(100)
FULLY_CLOSED: Final = Position(0)


def _as_position(value: JsonValue) -> Position:
    return Position(_as_int(value))


def _position_data(value: Position | None) -> int | None:
    return None if value is None else value.value


# ---------------------------------------------------------------------------
# Source values
# ---------------------------------------------------------------------------


type SourceScalar = bool | int | float | str
"""What a source can deliver once the adapter has read the entity."""


@unique
class SourceState(StrEnum):
    """The three states of a source value."""

    VALUE = "value"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class MissingSourceValueError(LookupError):
    """The value of a source was read although the source has none."""


class SourceValue[T: SourceScalar]:
    """An input read from a source: a value, unknown, or unavailable.

    Missing data is not good news. The type therefore has no truth value and
    no accessor that returns a default: ``bool(value)`` raises, numeric
    conversion is not defined, and :attr:`value` raises unless the state is
    :attr:`SourceState.VALUE`. Code that reads a source has to look at
    :attr:`state` first and say what "unknown" and "unavailable" mean for it.
    """

    __slots__ = ("_state", "_value")

    _state: SourceState
    _value: T | None

    def __init__(self, state: SourceState, value: T | None = None) -> None:
        """Create a source value; prefer :meth:`of`, :meth:`unknown`, :meth:`unavailable`."""
        _require_type(state, SourceState, "the state of a source value")
        if state is SourceState.VALUE:
            if value is None:
                raise ValueError("a source value in the state 'value' needs a value")
            if not isinstance(value, (bool, int, float, str)):
                raise TypeError(
                    "a source value must be a boolean, a number or a string, "
                    f"not {type(value).__name__}"
                )
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("a source value must be a finite number")
        elif value is not None:
            raise ValueError(
                f"a source value in the state {state.value!r} has no value"
            )
        object.__setattr__(self, "_state", state)
        object.__setattr__(self, "_value", value)

    @classmethod
    def of(cls, value: T) -> Self:
        """Return a source value that has a value."""
        return cls(SourceState.VALUE, value)

    @classmethod
    def unknown(cls) -> Self:
        """Return the source value "unknown"."""
        return cls(SourceState.UNKNOWN)

    @classmethod
    def unavailable(cls) -> Self:
        """Return the source value "unavailable"."""
        return cls(SourceState.UNAVAILABLE)

    @property
    def state(self) -> SourceState:
        """Return which of the three states this is."""
        return self._state

    @property
    def has_value(self) -> bool:
        """Return whether the state is :attr:`SourceState.VALUE`."""
        return self._state is SourceState.VALUE

    @property
    def value(self) -> T:
        """Return the value; raise if the source is unknown or unavailable."""
        if self._value is None:
            raise MissingSourceValueError(
                f"the source is {self._state.value}; it has no value"
            )
        return self._value

    def __bool__(self) -> NoReturn:
        """Refuse a truth value, so a missing input never reads as "off"."""
        raise TypeError(
            "a source value has no truth value; check its state and read its value"
        )

    def __setattr__(self, name: str, value: object) -> NoReturn:
        """Refuse assignment: source values are immutable."""
        raise AttributeError(f"cannot assign to {name!r}: source values are immutable")

    def __delattr__(self, name: str) -> NoReturn:
        """Refuse deletion: source values are immutable."""
        raise AttributeError(f"cannot delete {name!r}: source values are immutable")

    def __eq__(self, other: object) -> bool:
        """Compare state, value and the type of the value (``True`` is not ``1``)."""
        if not isinstance(other, SourceValue):
            return NotImplemented
        return (
            self._state is other._state
            and type(self._value) is type(other._value)
            and self._value == other._value
        )

    def __hash__(self) -> int:
        """Hash consistently with equality."""
        return hash((self._state, type(self._value), self._value))

    def __repr__(self) -> str:
        """Show the state, and the value if there is one."""
        if self._value is None:
            return f"SourceValue.{self._state.value}()"
        return f"SourceValue.of({self._value!r})"


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
        """Return the class of every wish of this layer."""
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
    """The target of one member; ``None`` means the member stays where it is."""

    member_id: str
    position: Position | None

    def __post_init__(self) -> None:
        """Validate the member identifier."""
        _require_identifier(self.member_id, "the member of a target")
        if self.position is not None:
            _require_type(self.position, Position, "the position of a target")


def _require_member_targets(
    targets: tuple[MemberTarget, ...], what: str, *, positions_required: bool
) -> None:
    for target in targets:
        _require_type(target, MemberTarget, what)
        if positions_required and target.position is None:
            raise ValueError(f"{what} must state a position for every member")
    _require_unique((target.member_id for target in targets), f"the members of {what}")


@dataclass(frozen=True, slots=True)
class Wish:
    """The answer of one layer: a target position, leave alone, or no opinion.

    ``position`` is the target of the window. A layer that decides per member
    (shading, decision 9) lists the members' positions in ``member_positions``
    and states the quantity it decided in as ``ray_height`` (metres above the
    floor); ``position`` is then the position of the first member.
    """

    layer: Layer
    kind: WishKind
    reason: ReasonCode
    position: Position | None = None
    direction: Direction | None = None
    member_positions: tuple[MemberTarget, ...] = ()
    ray_height: float | None = None

    def __post_init__(self) -> None:
        """Reject combinations that do not describe one of the three answers."""
        _require_type(self.layer, Layer, "the layer of a wish")
        _require_type(self.kind, WishKind, "the kind of a wish")
        _require_type(self.reason, ReasonCode, "the reason of a wish")
        object.__setattr__(self, "member_positions", tuple(self.member_positions))
        if self.kind is WishKind.TARGET:
            self._validate_target()
        elif (
            self.position is not None
            or self.direction is not None
            or self.member_positions
            or self.ray_height is not None
        ):
            raise ValueError(
                f"a wish of the kind {self.kind.value!r} carries no position, "
                "direction, member positions or ray height"
            )

    def _validate_target(self) -> None:
        if self.position is None:
            raise ValueError("a wish of the kind 'target' needs a position")
        _require_type(self.position, Position, "the position of a wish")
        if self.direction is not None:
            _require_type(self.direction, Direction, "the direction of a wish")
        _require_member_targets(
            self.member_positions,
            "the member positions of a wish",
            positions_required=True,
        )
        if self.member_positions and self.member_positions[0].position != self.position:
            raise ValueError(
                "the position of a wish must be the position of its first member"
            )
        if self.ray_height is not None:
            _require_finite(self.ray_height, "the ray height of a wish")

    @classmethod
    def target(  # noqa: PLR0913
        cls,
        layer: Layer,
        reason: ReasonCode,
        position: Position,
        *,
        direction: Direction | None = None,
        member_positions: Iterable[MemberTarget] = (),
        ray_height: float | None = None,
    ) -> Self:
        """Return a wish for a target position."""
        return cls(
            layer=layer,
            kind=WishKind.TARGET,
            reason=reason,
            position=position,
            direction=direction,
            member_positions=tuple(member_positions),
            ray_height=ray_height,
        )

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
        """Return the class of the wish, which follows from its layer."""
        return self.layer.wish_class


@dataclass(frozen=True, slots=True)
class LayerReason:
    """Why one layer did not win a recompute."""

    layer: Layer
    reason: ReasonCode

    def __post_init__(self) -> None:
        """Validate the types, so a reason is never free text."""
        _require_type(self.layer, Layer, "the layer of a layer reason")
        _require_type(self.reason, ReasonCode, "the reason of a layer reason")


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


@dataclass(frozen=True, slots=True)
class ConstraintResult:
    """What one constraint did to the winning wish.

    ``targets`` lists every member of the window with its target after this
    constraint. A member whose position is ``None`` was pinned: it stays where
    it is. A constraint that reports without changing anything (lockout
    protection that is void because of the tamper contact) repeats the targets
    it received.
    """

    constraint: Constraint
    reason: ReasonCode
    targets: tuple[MemberTarget, ...]

    def __post_init__(self) -> None:
        """Validate the types and the list of targets."""
        _require_type(self.constraint, Constraint, "the constraint of a result")
        _require_type(self.reason, ReasonCode, "the reason of a constraint result")
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
    where no rule applied. ``until`` is the point in time of a deferral; it is
    ``None`` when the deferral ends with a condition whose time is not known
    (a member becomes available, the members come to rest).

    For a window in dry-run, ``dry_run`` is true and the outcome is the
    hypothetical one: either the rule ``dry_run`` decided and ``would_send``
    lists the command that would have been sent, or ``rule`` names the earlier
    rule that would have held the wish back.
    """

    kind: GateKind
    reason: ReasonCode
    rule: GateRule | None = None
    until: datetime | None = None
    dry_run: bool = False
    would_send: tuple[MemberTarget, ...] = ()

    def __post_init__(self) -> None:
        """Reject outcomes that contradict themselves."""
        _require_type(self.kind, GateKind, "the kind of a gate outcome")
        _require_type(self.reason, ReasonCode, "the reason of a gate outcome")
        _require_type(self.dry_run, bool, "the dry-run flag of a gate outcome")
        _require_aware_or_none(self.until, "the end of a deferral")
        object.__setattr__(self, "would_send", tuple(self.would_send))
        _require_member_targets(
            self.would_send, "the would-be command", positions_required=True
        )
        if self.kind is GateKind.SEND:
            self._validate_send()
        else:
            self._validate_held_back()

    def _validate_send(self) -> None:
        if self.reason is not ReasonCode.SENT:
            raise ValueError("the outcome 'send' has the reason 'sent'")
        if self.rule is not None:
            raise ValueError("the outcome 'send' means that no gate rule applied")
        if self.until is not None or self.would_send:
            raise ValueError(
                "the outcome 'send' has no deferral and no would-be command"
            )
        if self.dry_run:
            raise ValueError("a window in dry-run never sends")

    def _validate_held_back(self) -> None:
        if self.reason is ReasonCode.SENT:
            raise ValueError("only the outcome 'send' has the reason 'sent'")
        if self.rule is None:
            raise ValueError("a deferral or a suppression names the rule that decided")
        _require_type(self.rule, GateRule, "the rule of a gate outcome")
        if self.until is not None and self.kind is not GateKind.DEFER:
            raise ValueError("only a deferral has an end")
        by_dry_run_rule = self.rule is GateRule.DRY_RUN
        if by_dry_run_rule != (self.reason is ReasonCode.DRY_RUN):
            raise ValueError(
                "the rule 'dry_run' and the reason 'dry_run' belong together"
            )
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
        until: datetime | None,
        *,
        dry_run: bool = False,
    ) -> Self:
        """Return the outcome "defer until"."""
        return cls(
            kind=GateKind.DEFER, reason=reason, rule=rule, until=until, dry_run=dry_run
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


@dataclass(frozen=True, slots=True)
class Decision:
    """The complete result of one recompute.

    - ``winning_wish``: the wish of the first layer with an opinion; ``None``
      if no layer had one (a window without a configured schedule).
    - ``other_layers``: for every other layer the reason why it did not win.
    - ``constraints``: the results of the constraints that applied, in order.
    - ``targets``: the target of every member after the constraints, the
      window's first member first. Empty if the winning wish is not a target.
      A member with the position ``None`` was pinned by a constraint.
    - ``gate``: the outcome of the gate; ``None`` if nothing reached the gate,
      because there is no target or a constraint pinned every member.
    """

    winning_wish: Wish | None
    other_layers: tuple[LayerReason, ...] = ()
    constraints: tuple[ConstraintResult, ...] = ()
    targets: tuple[MemberTarget, ...] = ()
    gate: GateOutcome | None = None

    def __post_init__(self) -> None:
        """Reject records whose parts contradict each other."""
        object.__setattr__(self, "other_layers", tuple(self.other_layers))
        object.__setattr__(self, "constraints", tuple(self.constraints))
        object.__setattr__(self, "targets", tuple(self.targets))
        self._validate_layers()
        for result in self.constraints:
            _require_type(result, ConstraintResult, "a constraint of a decision")
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
        self._validate_gate()

    def _validate_layers(self) -> None:
        if self.winning_wish is not None:
            _require_type(self.winning_wish, Wish, "the winning wish")
            if self.winning_wish.kind is WishKind.NO_OPINION:
                raise ValueError("a wish without an opinion cannot win")
        seen: set[Layer] = set()
        for entry in self.other_layers:
            _require_type(entry, LayerReason, "a layer reason of a decision")
            if entry.layer in seen:
                raise ValueError(f"the layer {entry.layer.value!r} is listed twice")
            seen.add(entry.layer)
        if self.winning_wish is not None and self.winning_wish.layer in seen:
            raise ValueError("the winning layer is not one of the other layers")

    def _validate_gate(self) -> None:
        to_send = tuple(
            target for target in self.targets if target.position is not None
        )
        if self.gate is None:
            if to_send:
                raise ValueError("a target that is not pinned reaches the gate")
            return
        _require_type(self.gate, GateOutcome, "the gate outcome of a decision")
        if not to_send:
            raise ValueError("nothing reaches the gate without a target to send")
        if self.gate.would_send and self.gate.would_send != to_send:
            raise ValueError("the would-be command consists of the decision's targets")

    @property
    def target(self) -> Position | None:
        """Return the target the window shows: that of its first member."""
        return self.targets[0].position if self.targets else None


# ---------------------------------------------------------------------------
# Members: capability profile, observation, own command
# ---------------------------------------------------------------------------


@unique
class CoveringType(StrEnum):
    """What hangs in front of the glass. Only roller shutters are implemented."""

    ROLLER_SHUTTER = "roller_shutter"


@unique
class PositionSource(StrEnum):
    """Where a reported position comes from; stated by the user."""

    MEASURED = "measured"
    """The drive itself measures the position."""
    CALCULATED = "calculated"
    """The actuator calculates the position from run time."""


@unique
class TransitReporting(StrEnum):
    """Whether a member reports that it is opening or closing."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"
    """Not observed yet."""


@unique
class PositionUpdates(StrEnum):
    """When a member reports its position during a movement."""

    LIVE = "live"
    END_ONLY = "end_only"


@unique
class PositionReference(StrEnum):
    """Whether a calculated position can be trusted (drift)."""

    REFERENCED = "referenced"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True, slots=True)
class CapabilityProfile:
    """What a member can do and report.

    A member that reports no position or cannot be set to a position is valid;
    it is operated in a degraded mode. Travel times are configuration values
    and are never learned from reports.
    """

    supports_open_close: bool
    supports_set_position: bool
    supports_stop: bool
    reports_position: bool
    travel_time_up: timedelta
    travel_time_down: timedelta
    position_source: PositionSource = PositionSource.CALCULATED
    reports_transit_states: TransitReporting = TransitReporting.UNKNOWN
    position_updates: PositionUpdates = PositionUpdates.END_ONLY
    report_delay: timedelta = timedelta(0)

    def __post_init__(self) -> None:
        """Validate types and durations."""
        for name in (
            "supports_open_close",
            "supports_set_position",
            "supports_stop",
            "reports_position",
        ):
            _require_type(getattr(self, name), bool, f"the capability {name!r}")
        _require_type(self.position_source, PositionSource, "the position source")
        _require_type(
            self.reports_transit_states, TransitReporting, "the transit reporting"
        )
        _require_type(self.position_updates, PositionUpdates, "the position updates")
        for name in ("travel_time_up", "travel_time_down"):
            travel_time = getattr(self, name)
            _require_type(travel_time, timedelta, f"the {name!r}")
            if travel_time <= timedelta(0):
                raise ValueError(f"the {name!r} must be longer than zero")
        _require_type(self.report_delay, timedelta, "the report delay")
        if self.report_delay < timedelta(0):
            raise ValueError("the report delay must not be negative")


@dataclass(frozen=True, slots=True)
class WindowCapabilities:
    """The capabilities of a window: the lowest common denominator of its members."""

    supports_open_close: bool
    supports_set_position: bool
    supports_stop: bool
    reports_position: bool


@unique
class MovementState(StrEnum):
    """The state class of an observation."""

    RESTING = "resting"
    MOVING_UP = "moving_up"
    MOVING_DOWN = "moving_down"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class Observation:
    """A normalized report of one member: state class and position, if any."""

    state: MovementState
    position: Position | None = None

    def __post_init__(self) -> None:
        """Reject a position on an unavailable member."""
        _require_type(self.state, MovementState, "the state of an observation")
        if self.position is not None:
            _require_type(self.position, Position, "the position of an observation")
            if self.state is MovementState.UNAVAILABLE:
                raise ValueError("an unavailable member has no position")

    @property
    def available(self) -> bool:
        """Return whether the member is available."""
        return self.state is not MovementState.UNAVAILABLE

    @property
    def moving(self) -> bool:
        """Return whether the member reports a movement."""
        return self.state in (MovementState.MOVING_UP, MovementState.MOVING_DOWN)

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {"state": self.state.value, "position": _position_data(self.position)}

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild an observation from plain data."""
        content = _as_object(data)
        return cls(
            state=_get(content, "state", _as_enum(MovementState)),
            position=_get(content, "position", _optional(_as_position)),
        )


@dataclass(frozen=True, slots=True)
class OwnCommand:
    """A command of the integration to one member: target, time and wish class."""

    target: Position
    time: datetime
    wish_class: WishClass

    def __post_init__(self) -> None:
        """Validate the types and reject a naive time."""
        _require_type(self.target, Position, "the target of a command")
        _require_aware(self.time, "the time of a command")
        _require_type(self.wish_class, WishClass, "the wish class of a command")

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "target": self.target.value,
            "time": self.time.isoformat(),
            "wish_class": self.wish_class.value,
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild a command from plain data."""
        content = _as_object(data)
        return cls(
            target=_get(content, "target", _as_position),
            time=_get(content, "time", _as_datetime),
            wish_class=_get(content, "wish_class", _as_enum(WishClass)),
        )


@dataclass(frozen=True, slots=True)
class MemberCommand:
    """A command together with the member it went to, or would have gone to."""

    member_id: str
    command: OwnCommand

    def __post_init__(self) -> None:
        """Validate the member identifier."""
        _require_identifier(self.member_id, "the member of a command")
        _require_type(self.command, OwnCommand, "the command of a member")

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {"member_id": self.member_id, "command": self.command.to_data()}

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild a member command from plain data."""
        content = _as_object(data)
        return cls(
            member_id=_get(content, "member_id", _as_str),
            command=_get(content, "command", OwnCommand.from_data),
        )


# ---------------------------------------------------------------------------
# Window configuration (resolved)
# ---------------------------------------------------------------------------


@unique
class ScheduleProfile(StrEnum):
    """The key under which the schedule looks up its targets.

    It has one value. The key exists so that an absence profile or named
    profiles can be added without restructuring.
    """

    DEFAULT = "default"


@dataclass(frozen=True, slots=True)
class TemperatureTier:
    """One tier of the temperature condition of shading: threshold and hysteresis."""

    threshold: float
    hysteresis: float

    def __post_init__(self) -> None:
        """Validate the numbers."""
        _require_finite(self.threshold, "the threshold of a temperature tier")
        _require_finite(self.hysteresis, "the hysteresis of a temperature tier")
        if self.hysteresis < 0:
            raise ValueError(
                "the hysteresis of a temperature tier must not be negative"
            )


@dataclass(frozen=True, slots=True)
class MemberConfig:
    """One cover of a window as the core sees it."""

    member_id: str
    capabilities: CapabilityProfile

    def __post_init__(self) -> None:
        """Validate the member identifier."""
        _require_identifier(self.member_id, "the identifier of a member")
        _require_type(
            self.capabilities, CapabilityProfile, "the capability profile of a member"
        )


@dataclass(frozen=True, slots=True)
class WindowConfig:
    """The configuration of one window after inheritance has been resolved.

    This block defines the parts all later blocks share: identity, covering
    type, members and the doors kept open. The blocks that build a feature add
    its settings.

    - ``morning_condition_source``: key of the source that has to hold before
      the morning opening (conditional morning opening). ``None`` means the
      condition is always fulfilled. No rule reads it yet.
    - ``shading_temperature_tiers``: the temperature condition of shading as a
      list of tiers. Only zero (no temperature condition) or one entry are
      accepted at present.
    - ``schedule_profile``: the key under which the schedule's targets are
      looked up; it has one value.
    """

    window_id: str
    members: tuple[MemberConfig, ...]
    covering_type: CoveringType = CoveringType.ROLLER_SHUTTER
    morning_condition_source: str | None = None
    shading_temperature_tiers: tuple[TemperatureTier, ...] = ()
    schedule_profile: ScheduleProfile = ScheduleProfile.DEFAULT

    def __post_init__(self) -> None:
        """Validate identity, members and the doors kept open."""
        _require_identifier(self.window_id, "the identifier of a window")
        object.__setattr__(self, "members", tuple(self.members))
        object.__setattr__(
            self, "shading_temperature_tiers", tuple(self.shading_temperature_tiers)
        )
        if not self.members:
            raise ValueError("a window has at least one member")
        for member in self.members:
            _require_type(member, MemberConfig, "a member of a window")
        _require_unique(
            (member.member_id for member in self.members), "the members of a window"
        )
        _require_type(self.covering_type, CoveringType, "the covering type")
        if self.morning_condition_source is not None:
            _require_identifier(
                self.morning_condition_source, "the source of the morning condition"
            )
        for tier in self.shading_temperature_tiers:
            _require_type(tier, TemperatureTier, "a temperature tier")
        if len(self.shading_temperature_tiers) > 1:
            raise ValueError("more than one temperature tier is not supported yet")
        _require_type(self.schedule_profile, ScheduleProfile, "the schedule profile")

    @property
    def capabilities(self) -> WindowCapabilities:
        """Return the lowest common denominator of the members' capabilities."""
        profiles = [member.capabilities for member in self.members]
        return WindowCapabilities(
            supports_open_close=all(p.supports_open_close for p in profiles),
            supports_set_position=all(p.supports_set_position for p in profiles),
            supports_stop=all(p.supports_stop for p in profiles),
            reports_position=all(p.reports_position for p in profiles),
        )


# ---------------------------------------------------------------------------
# Observed state of a window
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MemberObservation:
    """The current observation of one member."""

    member_id: str
    observation: Observation

    def __post_init__(self) -> None:
        """Validate the member identifier."""
        _require_identifier(self.member_id, "the member of an observation")
        _require_type(self.observation, Observation, "the observation of a member")


@dataclass(frozen=True, slots=True)
class WindowObservation:
    """The state of a window as observed: its members, and the view over them.

    The window is available while at least one member is, it is moving while
    at least one member reports a movement, and it shows the position of its
    first member. Whether a movement has settled is the tracker's knowledge
    and not part of this view.
    """

    members: tuple[MemberObservation, ...]

    def __post_init__(self) -> None:
        """Require at least one member and unique identifiers."""
        object.__setattr__(self, "members", tuple(self.members))
        if not self.members:
            raise ValueError("a window is observed through at least one member")
        for member in self.members:
            _require_type(member, MemberObservation, "a member observation")
        _require_unique(
            (member.member_id for member in self.members),
            "the members of a window observation",
        )

    @property
    def available(self) -> bool:
        """Return whether at least one member is available."""
        return any(member.observation.available for member in self.members)

    @property
    def moving(self) -> bool:
        """Return whether at least one member reports a movement."""
        return any(member.observation.moving for member in self.members)

    @property
    def position(self) -> Position | None:
        """Return the position of the first member, or ``None`` if it has none."""
        return self.members[0].observation.position


# ---------------------------------------------------------------------------
# Persisted window state
# ---------------------------------------------------------------------------


@unique
class PositionOwner(StrEnum):
    """Who put the window where it is."""

    ENGINE = "engine"
    USER = "user"
    UNKNOWN = "unknown"


@unique
class OverrideEndRule(StrEnum):
    """How a manual override ends by itself."""

    FIXED_MINUTES = "fixed_minutes"
    SHADING_EPISODE_END = "shading_episode_end"
    NEXT_PART_OF_DAY = "next_part_of_day"
    ROOM_EMPTY = "room_empty"


@unique
class DayType(StrEnum):
    """The type of a day, which selects the triggers of the schedule."""

    WORKDAY = "workday"
    WEEKEND = "weekend"
    HOLIDAY = "holiday"


@unique
class ProtectionEventStatus(StrEnum):
    """The persisted state of the trigger of a protection event."""

    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass(frozen=True, slots=True)
class MemberState:
    """What is persisted per member."""

    member_id: str
    last_own_command: OwnCommand | None = None
    last_observation: Observation | None = None
    position_reference: PositionReference = PositionReference.REFERENCED

    def __post_init__(self) -> None:
        """Validate the member identifier and the types."""
        _require_identifier(self.member_id, "the member of a member state")
        if self.last_own_command is not None:
            _require_type(self.last_own_command, OwnCommand, "the last own command")
        if self.last_observation is not None:
            _require_type(self.last_observation, Observation, "the last observation")
        _require_type(
            self.position_reference, PositionReference, "the position reference"
        )

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "member_id": self.member_id,
            "last_own_command": (
                None
                if self.last_own_command is None
                else self.last_own_command.to_data()
            ),
            "last_observation": (
                None
                if self.last_observation is None
                else self.last_observation.to_data()
            ),
            "position_reference": self.position_reference.value,
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild a member state from plain data."""
        content = _as_object(data)
        return cls(
            member_id=_get(content, "member_id", _as_str),
            last_own_command=_get(
                content, "last_own_command", _optional(OwnCommand.from_data)
            ),
            last_observation=_get(
                content, "last_observation", _optional(Observation.from_data)
            ),
            position_reference=_get(
                content, "position_reference", _as_enum(PositionReference)
            ),
        )


@dataclass(frozen=True, slots=True)
class ManualOverrideDam:
    """The armed manual override dam.

    ``ends_at`` is the absolute end if the end rule has one. The remembered
    position is ``None`` if the position the person chose is not known.
    """

    armed_at: datetime
    end_rule: OverrideEndRule
    ends_at: datetime | None = None
    remembered_position: Position | None = None

    def __post_init__(self) -> None:
        """Validate the types and reject naive datetimes."""
        _require_aware(self.armed_at, "the arming time of the manual override dam")
        _require_type(self.end_rule, OverrideEndRule, "the end rule of the dam")
        _require_aware_or_none(self.ends_at, "the end of the manual override dam")
        if self.remembered_position is not None:
            _require_type(self.remembered_position, Position, "the remembered position")

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "armed_at": self.armed_at.isoformat(),
            "end_rule": self.end_rule.value,
            "ends_at": _datetime_data(self.ends_at),
            "remembered_position": _position_data(self.remembered_position),
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the dam from plain data."""
        content = _as_object(data)
        return cls(
            armed_at=_get(content, "armed_at", _as_datetime),
            end_rule=_get(content, "end_rule", _as_enum(OverrideEndRule)),
            ends_at=_get(content, "ends_at", _optional(_as_datetime)),
            remembered_position=_get(
                content, "remembered_position", _optional(_as_position)
            ),
        )


@dataclass(frozen=True, slots=True)
class PersonAtWindowDam:
    """The armed person-at-the-window dam; it ends by itself."""

    ends_at: datetime

    def __post_init__(self) -> None:
        """Reject a naive datetime."""
        _require_aware(self.ends_at, "the end of the person-at-the-window dam")

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {"ends_at": self.ends_at.isoformat()}

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the dam from plain data."""
        return cls(ends_at=_get(_as_object(data), "ends_at", _as_datetime))


@dataclass(frozen=True, slots=True)
class ProtectionEventState:
    """What is persisted per protection event.

    The remembered position and owner are those the window had when the event
    started; a position that was not known is ``None``.
    """

    event_id: str
    status: ProtectionEventStatus = ProtectionEventStatus.INACTIVE
    active_since: datetime | None = None
    released: bool = False
    remembered_position: Position | None = None
    remembered_owner: PositionOwner | None = None

    def __post_init__(self) -> None:
        """Validate the types and reject naive datetimes."""
        _require_identifier(self.event_id, "the identifier of a protection event")
        _require_type(self.status, ProtectionEventStatus, "the status of an event")
        _require_aware_or_none(self.active_since, "the start of a protection event")
        _require_type(self.released, bool, "the released flag of an event")
        if self.remembered_position is not None:
            _require_type(self.remembered_position, Position, "the remembered position")
        if self.remembered_owner is not None:
            _require_type(self.remembered_owner, PositionOwner, "the remembered owner")

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "event_id": self.event_id,
            "status": self.status.value,
            "active_since": _datetime_data(self.active_since),
            "released": self.released,
            "remembered_position": _position_data(self.remembered_position),
            "remembered_owner": (
                None if self.remembered_owner is None else self.remembered_owner.value
            ),
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the state of a protection event from plain data."""
        content = _as_object(data)
        return cls(
            event_id=_get(content, "event_id", _as_str),
            status=_get(content, "status", _as_enum(ProtectionEventStatus)),
            active_since=_get(content, "active_since", _optional(_as_datetime)),
            released=_get(content, "released", _as_bool),
            remembered_position=_get(
                content, "remembered_position", _optional(_as_position)
            ),
            remembered_owner=_get(
                content, "remembered_owner", _optional(_as_enum(PositionOwner))
            ),
        )


@dataclass(frozen=True, slots=True)
class ShadingEpisodeState:
    """Persisted state of the shading episode; the rain lock can outlast it."""

    active_since: datetime | None = None
    rain_lock_until: datetime | None = None

    def __post_init__(self) -> None:
        """Reject naive datetimes."""
        _require_aware_or_none(self.active_since, "the start of the shading episode")
        _require_aware_or_none(self.rain_lock_until, "the end of the rain lock")

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "active_since": _datetime_data(self.active_since),
            "rain_lock_until": _datetime_data(self.rain_lock_until),
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the episode state from plain data."""
        content = _as_object(data)
        return cls(
            active_since=_get(content, "active_since", _optional(_as_datetime)),
            rain_lock_until=_get(content, "rain_lock_until", _optional(_as_datetime)),
        )


@dataclass(frozen=True, slots=True)
class SolarHeatingEpisodeState:
    """Persisted state of an active solar heating episode."""

    active_since: datetime
    opened_once: bool = False

    def __post_init__(self) -> None:
        """Reject a naive datetime."""
        _require_aware(self.active_since, "the start of the solar heating episode")
        _require_type(self.opened_once, bool, "the 'opened once' flag")

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "active_since": self.active_since.isoformat(),
            "opened_once": self.opened_once,
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the episode state from plain data."""
        content = _as_object(data)
        return cls(
            active_since=_get(content, "active_since", _as_datetime),
            opened_once=_get(content, "opened_once", _as_bool),
        )


@dataclass(frozen=True, slots=True)
class ExternalRequest:
    """A position requested by an automation, until it expires or is cleared.

    ``reason`` is the text the caller gave with the request. It is a subject
    attribute for status and events; a decision carries the reason code
    ``external_request`` and never this text.
    """

    position: Position
    reason: str
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate the types and reject a naive datetime."""
        _require_type(self.position, Position, "the position of a request")
        _require_type(self.reason, str, "the reason of a request")
        _require_aware_or_none(self.expires_at, "the expiry of a request")

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "position": self.position.value,
            "reason": self.reason,
            "expires_at": _datetime_data(self.expires_at),
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the request from plain data."""
        content = _as_object(data)
        return cls(
            position=_get(content, "position", _as_position),
            reason=_get(content, "reason", _as_str),
            expires_at=_get(content, "expires_at", _optional(_as_datetime)),
        )


@dataclass(frozen=True, slots=True)
class LatchedDayType:
    """The day type that was determined for one date and is kept for it."""

    day: date
    day_type: DayType

    def __post_init__(self) -> None:
        """Require a calendar date, not a point in time."""
        if isinstance(self.day, datetime):
            raise TypeError("a day type is latched for a date, not for a datetime")
        _require_type(self.day, date, "the date of a latched day type")
        _require_type(self.day_type, DayType, "the latched day type")

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {"day": self.day.isoformat(), "day_type": self.day_type.value}

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the latch from plain data."""
        content = _as_object(data)
        return cls(
            day=_get(content, "day", _as_date),
            day_type=_get(content, "day_type", _as_enum(DayType)),
        )


@dataclass(frozen=True, slots=True)
class HeldInput:
    """The last known value of an on/off input that is held, and when it was seen."""

    value: bool
    seen_at: datetime

    def __post_init__(self) -> None:
        """Validate the type and reject a naive datetime."""
        _require_type(self.value, bool, "the value of a held input")
        _require_aware(self.seen_at, "the time of a held input")

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {"value": self.value, "seen_at": self.seen_at.isoformat()}

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the held input from plain data."""
        content = _as_object(data)
        return cls(
            value=_get(content, "value", _as_bool),
            seen_at=_get(content, "seen_at", _as_datetime),
        )


@dataclass(frozen=True, slots=True)
class SimulatedState:
    """The would-be commands of a window in dry-run.

    It is kept apart from the real state, so the real motor protection clock
    is never touched, and it is discarded when the window is armed.
    """

    commands: tuple[MemberCommand, ...] = ()
    last_comfort_movement: datetime | None = None

    def __post_init__(self) -> None:
        """Validate the commands and reject a naive datetime."""
        object.__setattr__(self, "commands", tuple(self.commands))
        for command in self.commands:
            _require_type(command, MemberCommand, "a simulated command")
        _require_unique(
            (command.member_id for command in self.commands),
            "the members of the simulated commands",
        )
        _require_aware_or_none(
            self.last_comfort_movement, "the simulated motor protection clock"
        )

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "commands": [command.to_data() for command in self.commands],
            "last_comfort_movement": _datetime_data(self.last_comfort_movement),
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the simulated state from plain data."""
        content = _as_object(data)
        return cls(
            commands=_get(content, "commands", _tuple_of(MemberCommand.from_data)),
            last_comfort_movement=_get(
                content, "last_comfort_movement", _optional(_as_datetime)
            ),
        )


@dataclass(frozen=True, slots=True)
class WindowState:
    """Everything a window has to remember between recomputes and restarts.

    ``WindowState()`` is the state of a window that has just been set up. The
    held state of a protection trigger is part of its
    :class:`ProtectionEventState`; ``held_frost`` (true = frost) and
    ``held_season`` (true = summer) are the other inputs that are held.
    ``simulated`` exists only while the window is in dry-run.
    """

    owner: PositionOwner = PositionOwner.UNKNOWN
    members: tuple[MemberState, ...] = ()
    manual_override: ManualOverrideDam | None = None
    person_at_window: PersonAtWindowDam | None = None
    protection_events: tuple[ProtectionEventState, ...] = ()
    fire_unacknowledged: bool = False
    shading_episode: ShadingEpisodeState | None = None
    solar_heating_episode: SolarHeatingEpisodeState | None = None
    external_request: ExternalRequest | None = None
    latched_day_types: tuple[LatchedDayType, ...] = ()
    last_comfort_movement: datetime | None = None
    held_frost: HeldInput | None = None
    held_season: HeldInput | None = None
    frost_waiver_until: datetime | None = None
    simulated: SimulatedState | None = None

    def __post_init__(self) -> None:
        """Validate the lists and reject naive datetimes."""
        _require_type(self.owner, PositionOwner, "the owner of the position")
        object.__setattr__(self, "members", tuple(self.members))
        object.__setattr__(self, "protection_events", tuple(self.protection_events))
        object.__setattr__(self, "latched_day_types", tuple(self.latched_day_types))
        for member in self.members:
            _require_type(member, MemberState, "a member state")
        _require_unique(
            (member.member_id for member in self.members),
            "the members of a window state",
        )
        for event in self.protection_events:
            _require_type(event, ProtectionEventState, "a protection event state")
        _require_unique(
            (event.event_id for event in self.protection_events),
            "the protection events of a window state",
        )
        _require_type(self.fire_unacknowledged, bool, "the fire flag")
        for latch in self.latched_day_types:
            _require_type(latch, LatchedDayType, "a latched day type")
        if len(self.latched_day_types) > _MAX_LATCHED_DAY_TYPES:
            raise ValueError("day types are latched for today and tomorrow only")
        _require_unique(
            (latch.day.isoformat() for latch in self.latched_day_types),
            "the dates of the latched day types",
        )
        _require_aware_or_none(
            self.last_comfort_movement, "the time of the last comfort movement"
        )
        _require_aware_or_none(self.frost_waiver_until, "the end of the frost waiver")

    def to_data(self) -> JsonObject:
        """Return plain, JSON-compatible data with the schema version."""
        return {
            "schema_version": WINDOW_STATE_SCHEMA_VERSION,
            "owner": self.owner.value,
            "members": [member.to_data() for member in self.members],
            "manual_override": (
                None if self.manual_override is None else self.manual_override.to_data()
            ),
            "person_at_window": (
                None
                if self.person_at_window is None
                else self.person_at_window.to_data()
            ),
            "protection_events": [event.to_data() for event in self.protection_events],
            "fire_unacknowledged": self.fire_unacknowledged,
            "shading_episode": (
                None if self.shading_episode is None else self.shading_episode.to_data()
            ),
            "solar_heating_episode": (
                None
                if self.solar_heating_episode is None
                else self.solar_heating_episode.to_data()
            ),
            "external_request": (
                None
                if self.external_request is None
                else self.external_request.to_data()
            ),
            "latched_day_types": [latch.to_data() for latch in self.latched_day_types],
            "last_comfort_movement": _datetime_data(self.last_comfort_movement),
            "held_frost": None
            if self.held_frost is None
            else self.held_frost.to_data(),
            "held_season": (
                None if self.held_season is None else self.held_season.to_data()
            ),
            "frost_waiver_until": _datetime_data(self.frost_waiver_until),
            "simulated": None if self.simulated is None else self.simulated.to_data(),
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild a window state from plain data of the current schema version.

        Data of another version is refused; migrating it is the job of the
        persistence module.
        """
        content = _as_object(data)
        version = _get(content, "schema_version", _as_int)
        if version != WINDOW_STATE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema version {version}, "
                f"expected {WINDOW_STATE_SCHEMA_VERSION}"
            )
        return cls(
            owner=_get(content, "owner", _as_enum(PositionOwner)),
            members=_get(content, "members", _tuple_of(MemberState.from_data)),
            manual_override=_get(
                content, "manual_override", _optional(ManualOverrideDam.from_data)
            ),
            person_at_window=_get(
                content, "person_at_window", _optional(PersonAtWindowDam.from_data)
            ),
            protection_events=_get(
                content, "protection_events", _tuple_of(ProtectionEventState.from_data)
            ),
            fire_unacknowledged=_get(content, "fire_unacknowledged", _as_bool),
            shading_episode=_get(
                content, "shading_episode", _optional(ShadingEpisodeState.from_data)
            ),
            solar_heating_episode=_get(
                content,
                "solar_heating_episode",
                _optional(SolarHeatingEpisodeState.from_data),
            ),
            external_request=_get(
                content, "external_request", _optional(ExternalRequest.from_data)
            ),
            latched_day_types=_get(
                content, "latched_day_types", _tuple_of(LatchedDayType.from_data)
            ),
            last_comfort_movement=_get(
                content, "last_comfort_movement", _optional(_as_datetime)
            ),
            held_frost=_get(content, "held_frost", _optional(HeldInput.from_data)),
            held_season=_get(content, "held_season", _optional(HeldInput.from_data)),
            frost_waiver_until=_get(
                content, "frost_waiver_until", _optional(_as_datetime)
            ),
            simulated=_get(content, "simulated", _optional(SimulatedState.from_data)),
        )


# ---------------------------------------------------------------------------
# World snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SunPosition:
    """Where the sun is: azimuth clockwise from north and elevation, in degrees."""

    azimuth: float
    elevation: float

    def __post_init__(self) -> None:
        """Validate the ranges."""
        _require_finite(self.azimuth, "the azimuth of the sun")
        _require_finite(self.elevation, "the elevation of the sun")
        if not 0 <= self.azimuth < _FULL_CIRCLE:
            raise ValueError("the azimuth must be at least 0 and below 360 degrees")
        if not -_ZENITH <= self.elevation <= _ZENITH:
            raise ValueError("the elevation must be within -90 and 90 degrees")


type AnySourceValue = (
    SourceValue[bool] | SourceValue[int] | SourceValue[float] | SourceValue[str]
)
"""A source value of any of the scalar types."""


@dataclass(frozen=True, slots=True)
class WorldSnapshot:
    """Everything one recompute may look at.

    ``sources`` maps the key of a source to its value. The mapping is copied
    and cannot be changed afterwards. A snapshot is compared by value, but it
    is not hashable, because it contains a mapping.
    """

    time: datetime
    sun: SunPosition
    sources: Mapping[str, AnySourceValue]
    observation: WindowObservation
    state: WindowState

    def __post_init__(self) -> None:
        """Reject a naive time and copy the sources."""
        _require_aware(self.time, "the time of a world snapshot")
        _require_type(self.sun, SunPosition, "the sun position of a snapshot")
        _require_type(self.observation, WindowObservation, "the observed window")
        _require_type(self.state, WindowState, "the persisted window state")
        sources = dict(self.sources)
        for key, value in sources.items():
            _require_identifier(key, "the key of a source")
            _require_type(value, SourceValue, f"the source {key!r}")
        object.__setattr__(self, "sources", MappingProxyType(sources))
