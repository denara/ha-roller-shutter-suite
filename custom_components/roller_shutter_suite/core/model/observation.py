"""Observations of members, the view of a window over them, and own commands."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique
from typing import Self

from custom_components.roller_shutter_suite.core.reasons import (
    ReasonCategory,
    ReasonCode,
)

from ._data import (
    JsonObject,
    JsonValue,
    as_datetime,
    as_enum,
    as_object,
    as_str,
    optional,
    read,
)
from ._validation import (
    require_identifier,
    require_optional_type,
    require_type,
    require_unique,
    to_utc,
)
from .decision import WishClass
from .values import Position, _as_position, _position_data
from .window import MIN_TOLERANCE

# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------


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
        require_type(self.state, MovementState, "the state of an observation")
        if self.position is not None:
            require_type(self.position, Position, "the position of an observation")
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
        content = as_object(data, "state", "position")
        return cls(
            state=read(content, "state", as_enum(MovementState)),
            position=read(content, "position", optional(_as_position)),
        )


@dataclass(frozen=True, slots=True)
class MemberObservation:
    """The current observation of one member."""

    member_id: str
    observation: Observation

    def __post_init__(self) -> None:
        """Validate the member identifier."""
        require_identifier(self.member_id, "the member of an observation")
        require_type(self.observation, Observation, "the observation of a member")


@unique
class MembersAtTargets(StrEnum):
    """Whether every member stands at its own last commanded target."""

    YES = "yes"
    NO = "no"
    CANNOT_BE_JUDGED = "cannot_be_judged"


@dataclass(frozen=True, slots=True)
class WindowObservation:
    """The state of a window as observed: its members, and the view over them.

    The window is available while at least one member is, and it reports a
    movement as soon as one member does. Whether a movement has *settled* is
    the tracker's knowledge and not part of this view. The position of the
    window is not a property, because it depends on the members'
    tolerances: see :meth:`position`.
    """

    members: tuple[MemberObservation, ...]

    def __post_init__(self) -> None:
        """Require at least one member and unique identifiers."""
        object.__setattr__(self, "members", tuple(self.members))
        if not self.members:
            raise ValueError("a window is observed through at least one member")
        for member in self.members:
            require_type(member, MemberObservation, "a member observation")
        require_unique(
            (member.member_id for member in self.members),
            "the members of a window observation",
        )

    @property
    def available(self) -> bool:
        """Return whether at least one member is available."""
        return any(member.observation.available for member in self.members)

    @property
    def reports_movement(self) -> bool:
        """Return whether at least one member reports a movement."""
        return any(member.observation.moving for member in self.members)

    def _reports(
        self, tolerances: Mapping[str, int]
    ) -> list[tuple[str, Position | None, int]]:
        """Validate the tolerances; return (member, report, tolerance) per member."""
        rows: list[tuple[str, Position | None, int]] = []
        for member in self.members:
            if member.member_id not in tolerances:
                raise ValueError(f"no tolerance given for {member.member_id!r}")
            tolerance = tolerances[member.member_id]
            if isinstance(tolerance, bool) or not isinstance(tolerance, int):
                raise TypeError(f"the tolerance of {member.member_id!r} is no integer")
            if tolerance < MIN_TOLERANCE:
                raise ValueError(
                    f"the tolerance of {member.member_id!r} is below the minimum "
                    f"of {MIN_TOLERANCE}"
                )
            rows.append((member.member_id, member.observation.position, tolerance))
        return rows

    def position(self, tolerances: Mapping[str, int]) -> Position | None:
        """Return the position of the window, or ``None`` if it has none.

        The window has a position, one number, as soon as all members report
        the same position within tolerance, whatever was commanded last.
        Otherwise it has none; the members' values stay available
        individually. No member speaks for the window.

        1. Every member reports a position. A member without position feedback
           or an unavailable member means that the window has no position.
        2. The highest and the lowest report differ by no more than the
           tolerance. If the members have different tolerances, the smallest
           one applies.
        3. The position is the mean of the reports, rounded half up.

        A window with a single member therefore has a position whenever its
        member reports one, also right after a movement by hand.
        ``tolerances`` gives the tolerance of every member, at least 1
        (``CapabilityProfile.tolerance``).

        A position may be returned while a member still reports a movement.
        Rest is not required here: "settled" is knowledge of the movement
        tracker. Whether the members are where they were commanded to is a
        separate statement: :meth:`members_at_commanded_targets`.
        """
        rows = self._reports(tolerances)
        reports = [reported.value for _, reported, _ in rows if reported is not None]
        if len(reports) != len(rows):
            return None
        if max(reports) - min(reports) > min(tolerance for _, _, tolerance in rows):
            return None
        return Position((2 * sum(reports) + len(reports)) // (2 * len(reports)))

    def members_at_commanded_targets(
        self, commanded: Mapping[str, Position], tolerances: Mapping[str, int]
    ) -> MembersAtTargets:
        """Say whether every member stands at its own last commanded target.

        Each member is compared with its own target within its own tolerance.
        The targets may differ between members (shading with unequal glass):
        the answer is still "yes", although the window then has no single
        position. This is what tells "everything is where it should be" apart
        from "something is off" when :meth:`position` returns ``None``.

        ``commanded`` maps a member to the target of its last own command as
        the persisted state has it (``WindowState.commanded_targets``); a
        member that was never commanded has no entry. A member can be judged
        if it reports a position and has a last commanded target.

        - "no": a member that can be judged stands outside its tolerance. One
          "no" refutes "all members are at their targets", so it takes
          precedence over members that cannot be judged.
        - "cannot be judged": no member says "no", but at least one cannot be
          judged: it reports no position (no position feedback, or
          unavailable) or was never commanded.
        - "yes": every member can be judged and stands at its target.

        A member that still reports a movement is compared like any other;
        whether a movement has settled is the tracker's knowledge.
        """
        known = {member.member_id for member in self.members}
        for member_id in commanded:
            if member_id not in known:
                raise ValueError(
                    f"a commanded target names {member_id!r}, which is not a "
                    "member of this window"
                )
        answer = MembersAtTargets.YES
        for member_id, reported, tolerance in self._reports(tolerances):
            target = commanded.get(member_id)
            if reported is None or target is None:
                answer = MembersAtTargets.CANNOT_BE_JUDGED
            elif abs(reported.value - target.value) > tolerance:
                return MembersAtTargets.NO
        return answer


# ---------------------------------------------------------------------------
# Own commands
# ---------------------------------------------------------------------------


@unique
class TravelDirection(StrEnum):
    """The direction of a commanded movement."""

    UP = "up"
    DOWN = "down"


@dataclass(frozen=True, slots=True)
class OwnCommand:
    """A command of the integration to one member.

    - ``command_id``: the identifier the engine gave the command. The actuator
      port receives it and the result of the command comes back with it, so a
      late result of an older command is never attributed to a newer one.
    - ``target``, ``direction``, ``time``, ``wish_class``: what the movement
      tracker remembers about an own command.
    - ``reason``: the reason code of the wish that caused the command, a code
      of the group "winning or contributing layers". **The reason on the
      command is authoritative** for what the movement is; a decision only
      documents its moment. When a wish of a higher class takes a movement in
      flight over, class and reason of the command change to those of that
      wish.
    - ``context_id``: the identifier under which the outside world executed
      the command (in Home Assistant the context of the service call). It is
      known only once the result has come back, and it is a hint for
      diagnostics, never a decision.

    The time is an instant and is kept in UTC.
    """

    command_id: str
    target: Position
    direction: TravelDirection
    time: datetime
    wish_class: WishClass
    reason: ReasonCode
    context_id: str | None = None

    def __post_init__(self) -> None:
        """Validate the types, reject a naive time and keep the instant in UTC."""
        require_identifier(self.command_id, "the identifier of a command")
        require_type(self.target, Position, "the target of a command")
        require_type(self.direction, TravelDirection, "the direction of a command")
        object.__setattr__(self, "time", to_utc(self.time, "the time of a command"))
        require_type(self.wish_class, WishClass, "the wish class of a command")
        require_type(self.reason, ReasonCode, "the reason of a command")
        if self.reason.category is not ReasonCategory.LAYER:
            raise ValueError(
                "the reason of a command is the reason of the wish that caused it, "
                f"a code of the group 'layer'; {self.reason.value!r} belongs to "
                f"{self.reason.category.value!r}"
            )
        require_optional_type(self.context_id, str, "the context of a command")

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "command_id": self.command_id,
            "target": self.target.value,
            "direction": self.direction.value,
            "time": self.time.isoformat(),
            "wish_class": self.wish_class.value,
            "reason": self.reason.value,
            "context_id": self.context_id,
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild a command from plain data."""
        content = as_object(
            data,
            "command_id",
            "target",
            "direction",
            "time",
            "wish_class",
            "reason",
            "context_id",
        )
        return cls(
            command_id=read(content, "command_id", as_str),
            target=read(content, "target", _as_position),
            direction=read(content, "direction", as_enum(TravelDirection)),
            time=read(content, "time", as_datetime),
            wish_class=read(content, "wish_class", as_enum(WishClass)),
            reason=read(content, "reason", as_enum(ReasonCode)),
            context_id=read(content, "context_id", optional(as_str)),
        )


@dataclass(frozen=True, slots=True)
class MemberCommand:
    """A command together with the member it went to, or would have gone to."""

    member_id: str
    command: OwnCommand

    def __post_init__(self) -> None:
        """Validate the member identifier."""
        require_identifier(self.member_id, "the member of a command")
        require_type(self.command, OwnCommand, "the command of a member")

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {"member_id": self.member_id, "command": self.command.to_data()}

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild a member command from plain data."""
        content = as_object(data, "member_id", "command")
        return cls(
            member_id=read(content, "member_id", as_str),
            command=read(content, "command", OwnCommand.from_data),
        )
