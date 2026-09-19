"""Observations of members, the view of a window over them, and own commands."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique
from typing import Self

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
from .values import Position, as_position, position_data

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
        return {"state": self.state.value, "position": position_data(self.position)}

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild an observation from plain data."""
        content = as_object(data, "state", "position")
        return cls(
            state=read(content, "state", as_enum(MovementState)),
            position=read(content, "position", optional(as_position)),
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


@dataclass(frozen=True, slots=True)
class WindowObservation:
    """The state of a window as observed: its members, and the view over them.

    The window is available while at least one member is, and it reports a
    movement as soon as one member does. Whether a movement has *settled* is
    the tracker's knowledge and not part of this view. The position of the
    window is not a property, because it depends on the members' last
    commanded targets and tolerances: see :meth:`position`.
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

    def position(
        self, commanded: Mapping[str, Position], tolerances: Mapping[str, int]
    ) -> Position | None:
        """Return the logical position of the window, or ``None`` if it has none.

        A window has a position only when every member stands at its own last
        commanded target within its own tolerance. No member speaks for the
        window; the members' values stay available individually in any case.

        ``commanded`` maps a member to the target of its last own command as
        the persisted state has it (``WindowState.commanded_targets``); a
        member that was never commanded has no entry. ``tolerances`` gives the
        tolerance of every member. ``WorldSnapshot.window_position`` calls
        this with the persisted state of the snapshot.

        1. Every member reports a position; otherwise there is none.
        2. If no member was ever commanded, the window has a position only if
           all members report the same position within tolerance: the highest
           and the lowest report differ by no more than the smallest
           tolerance. It is then the mean of the reports, rounded half up.
        3. If some members have a last command and others do not, there is
           none.
        4. Otherwise every member stands within its tolerance of its own
           target, or there is none. The position is the common target. If
           the members' targets differ (shading with unequal glass), there is
           no single number, so there is none.

        Rules 1 to 4 were decided by the project owner, except two readings
        of this block: the rounded mean as the value in rule 2, and "none"
        for members that stand at different targets in rule 4.
        """
        known = {member.member_id for member in self.members}
        for member_id in commanded:
            if member_id not in known:
                raise ValueError(
                    f"a commanded target names {member_id!r}, which is not a "
                    "member of this window"
                )
        reports: list[int] = []
        limits: list[int] = []
        at_target = True
        for member in self.members:
            if member.member_id not in tolerances:
                raise ValueError(f"no tolerance given for {member.member_id!r}")
            tolerance = tolerances[member.member_id]
            reported = member.observation.position
            if reported is None:
                return None
            target = commanded.get(member.member_id)
            if target is not None and abs(reported.value - target.value) > tolerance:
                at_target = False
            reports.append(reported.value)
            limits.append(tolerance)
        if not commanded:
            if max(reports) - min(reports) > min(limits):
                return None
            return Position((2 * sum(reports) + len(reports)) // (2 * len(reports)))
        targets = set(commanded.values())
        if len(commanded) != len(self.members) or not at_target or len(targets) != 1:
            return None
        return next(iter(targets))


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
    context_id: str | None = None

    def __post_init__(self) -> None:
        """Validate the types, reject a naive time and keep the instant in UTC."""
        require_identifier(self.command_id, "the identifier of a command")
        require_type(self.target, Position, "the target of a command")
        require_type(self.direction, TravelDirection, "the direction of a command")
        object.__setattr__(self, "time", to_utc(self.time, "the time of a command"))
        require_type(self.wish_class, WishClass, "the wish class of a command")
        require_optional_type(self.context_id, str, "the context of a command")

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "command_id": self.command_id,
            "target": self.target.value,
            "direction": self.direction.value,
            "time": self.time.isoformat(),
            "wish_class": self.wish_class.value,
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
            "context_id",
        )
        return cls(
            command_id=read(content, "command_id", as_str),
            target=read(content, "target", as_position),
            direction=read(content, "direction", as_enum(TravelDirection)),
            time=read(content, "time", as_datetime),
            wish_class=read(content, "wish_class", as_enum(WishClass)),
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
