"""The persisted window state and its round trip through plain data.

Everything here is an instant or a flag that has to survive a restart. Every
datetime is kept in UTC, so a state that went through plain data compares
equal to the one that was written, also in the repeated hour of a clock change.
"""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum, unique
from typing import Final, Self

from ._data import (
    JsonObject,
    JsonValue,
    as_bool,
    as_date,
    as_datetime,
    as_enum,
    as_int,
    as_object,
    as_str,
    datetime_data,
    optional,
    read,
    tuple_of,
)
from ._validation import (
    require_identifier,
    require_optional_type,
    require_type,
    require_unique,
    to_utc,
    to_utc_or_none,
)
from .observation import MemberCommand, Observation, OwnCommand
from .values import Position, _as_position, _position_data

WINDOW_STATE_SCHEMA_VERSION: Final = 1
"""Version of the plain data layout written by :meth:`WindowState.to_data`."""

_MAX_LATCHED_DAY_TYPES: Final = 2


@unique
class PositionReference(StrEnum):
    """Whether a calculated position can be trusted (drift)."""

    REFERENCED = "referenced"
    UNCERTAIN = "uncertain"


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
    """What is persisted per member.

    The last own command stays here with its target: the question whether
    the members stand where they were commanded to, and the comparison after
    a restart, both need the last commanded target of every member.

    The command backoff is persisted as facts: ``command_attempts`` is the
    number of attempts of the current command, ``last_attempt_at`` the time of
    the last one. The time of the next retry is not stored; it is computed
    from these two facts with the settings that apply then, so a reload right
    after a failed attempt does not trigger an immediate second command. The
    two belong together: no attempt, no time; at least one attempt, a time.
    """

    member_id: str
    last_own_command: OwnCommand | None = None
    last_observation: Observation | None = None
    position_reference: PositionReference = PositionReference.REFERENCED
    command_attempts: int = 0
    last_attempt_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate the member identifier and the types."""
        require_identifier(self.member_id, "the member of a member state")
        if self.last_own_command is not None:
            require_type(self.last_own_command, OwnCommand, "the last own command")
        if self.last_observation is not None:
            require_type(self.last_observation, Observation, "the last observation")
        require_type(
            self.position_reference, PositionReference, "the position reference"
        )
        if isinstance(self.command_attempts, bool) or not isinstance(
            self.command_attempts, int
        ):
            raise TypeError("the number of command attempts must be an integer")
        if self.command_attempts < 0:
            raise ValueError("the number of command attempts must not be negative")
        object.__setattr__(
            self,
            "last_attempt_at",
            to_utc_or_none(self.last_attempt_at, "the time of the last attempt"),
        )
        if self.command_attempts > 0 and self.last_own_command is None:
            raise ValueError(
                "command attempts are attempts of the current command; without "
                "a last own command there are none"
            )
        if (self.command_attempts == 0) != (self.last_attempt_at is None):
            raise ValueError(
                "the number of command attempts and the time of the last attempt "
                "belong together: no attempt, no time; an attempt, a time"
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
            "command_attempts": self.command_attempts,
            "last_attempt_at": datetime_data(self.last_attempt_at),
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild a member state from plain data."""
        content = as_object(
            data,
            "member_id",
            "last_own_command",
            "last_observation",
            "position_reference",
            "command_attempts",
            "last_attempt_at",
        )
        return cls(
            member_id=read(content, "member_id", as_str),
            last_own_command=read(
                content, "last_own_command", optional(OwnCommand.from_data)
            ),
            last_observation=read(
                content, "last_observation", optional(Observation.from_data)
            ),
            position_reference=read(
                content, "position_reference", as_enum(PositionReference)
            ),
            command_attempts=read(content, "command_attempts", as_int),
            last_attempt_at=read(content, "last_attempt_at", optional(as_datetime)),
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
        object.__setattr__(
            self,
            "armed_at",
            to_utc(self.armed_at, "the arming time of the manual override dam"),
        )
        require_type(self.end_rule, OverrideEndRule, "the end rule of the dam")
        object.__setattr__(
            self,
            "ends_at",
            to_utc_or_none(self.ends_at, "the end of the manual override dam"),
        )
        if self.remembered_position is not None:
            require_type(self.remembered_position, Position, "the remembered position")

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "armed_at": self.armed_at.isoformat(),
            "end_rule": self.end_rule.value,
            "ends_at": datetime_data(self.ends_at),
            "remembered_position": _position_data(self.remembered_position),
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the dam from plain data."""
        content = as_object(
            data, "armed_at", "end_rule", "ends_at", "remembered_position"
        )
        return cls(
            armed_at=read(content, "armed_at", as_datetime),
            end_rule=read(content, "end_rule", as_enum(OverrideEndRule)),
            ends_at=read(content, "ends_at", optional(as_datetime)),
            remembered_position=read(
                content, "remembered_position", optional(_as_position)
            ),
        )


@dataclass(frozen=True, slots=True)
class PersonAtWindowDam:
    """The armed person-at-the-window dam; it ends by itself."""

    ends_at: datetime

    def __post_init__(self) -> None:
        """Reject a naive datetime."""
        object.__setattr__(
            self,
            "ends_at",
            to_utc(self.ends_at, "the end of the person-at-the-window dam"),
        )

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {"ends_at": self.ends_at.isoformat()}

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the dam from plain data."""
        return cls(ends_at=read(as_object(data, "ends_at"), "ends_at", as_datetime))


@dataclass(frozen=True, slots=True)
class ProtectionEventState:
    """What is persisted per protection event.

    - An active event has ``active_since`` and no ``ended_at``.
    - An inactive event has no ``active_since``; its ``ended_at`` is the time
      its last activation ended, or ``None`` if it never was active or the
      return after the event has been completed.
    - ``released_at`` is the time at which the watchdog released the event. A
      released event is still active as long as its trigger is; an inactive
      event can still carry ``released_at`` if it was released before its
      trigger ended. ``released`` is the read-only view "``released_at`` is
      set"; there is no second flag that could contradict it.

    End and release are persisted as times, not as deadlines: the waiting time
    of the return is configuration and is applied when it is evaluated. It
    runs from :attr:`return_clock_start`: the release if there was one,
    otherwise the end.

    The remembered position and owner are those the window had when the event
    started; a position that was not known is ``None``.
    """

    event_id: str
    status: ProtectionEventStatus = ProtectionEventStatus.INACTIVE
    active_since: datetime | None = None
    ended_at: datetime | None = None
    released_at: datetime | None = None
    remembered_position: Position | None = None
    remembered_owner: PositionOwner | None = None

    def __post_init__(self) -> None:
        """Validate the types and reject naive datetimes."""
        require_identifier(self.event_id, "the identifier of a protection event")
        require_type(self.status, ProtectionEventStatus, "the status of an event")
        object.__setattr__(
            self,
            "active_since",
            to_utc_or_none(self.active_since, "the start of a protection event"),
        )
        object.__setattr__(
            self,
            "ended_at",
            to_utc_or_none(self.ended_at, "the end of a protection event"),
        )
        if self.status is ProtectionEventStatus.ACTIVE:
            if self.active_since is None:
                raise ValueError("an active protection event states since when")
            if self.ended_at is not None:
                raise ValueError("an active protection event has not ended")
        elif self.active_since is not None:
            raise ValueError("an inactive protection event is not active since a time")
        object.__setattr__(
            self,
            "released_at",
            to_utc_or_none(self.released_at, "the release of a protection event"),
        )
        if self.remembered_position is not None:
            require_type(self.remembered_position, Position, "the remembered position")
        if self.remembered_owner is not None:
            require_type(self.remembered_owner, PositionOwner, "the remembered owner")

    @property
    def released(self) -> bool:
        """Return whether the watchdog released the event."""
        return self.released_at is not None

    @property
    def return_clock_start(self) -> datetime | None:
        """Return the time from which the waiting time of the return runs.

        It is the release if the watchdog released the event, otherwise the
        end of the event; ``None`` if there is neither.
        """
        return self.released_at if self.released_at is not None else self.ended_at

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "event_id": self.event_id,
            "status": self.status.value,
            "active_since": datetime_data(self.active_since),
            "ended_at": datetime_data(self.ended_at),
            "released_at": datetime_data(self.released_at),
            "remembered_position": _position_data(self.remembered_position),
            "remembered_owner": (
                None if self.remembered_owner is None else self.remembered_owner.value
            ),
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the state of a protection event from plain data."""
        content = as_object(
            data,
            "event_id",
            "status",
            "active_since",
            "ended_at",
            "released_at",
            "remembered_position",
            "remembered_owner",
        )
        return cls(
            event_id=read(content, "event_id", as_str),
            status=read(content, "status", as_enum(ProtectionEventStatus)),
            active_since=read(content, "active_since", optional(as_datetime)),
            ended_at=read(content, "ended_at", optional(as_datetime)),
            released_at=read(content, "released_at", optional(as_datetime)),
            remembered_position=read(
                content, "remembered_position", optional(_as_position)
            ),
            remembered_owner=read(
                content, "remembered_owner", optional(as_enum(PositionOwner))
            ),
        )


@dataclass(frozen=True, slots=True)
class ShadingEpisodeState:
    """Persisted state of the shading episode; the rain lock can outlast it."""

    active_since: datetime | None = None
    rain_lock_until: datetime | None = None

    def __post_init__(self) -> None:
        """Reject naive datetimes."""
        object.__setattr__(
            self,
            "active_since",
            to_utc_or_none(self.active_since, "the start of the shading episode"),
        )
        object.__setattr__(
            self,
            "rain_lock_until",
            to_utc_or_none(self.rain_lock_until, "the end of the rain lock"),
        )

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "active_since": datetime_data(self.active_since),
            "rain_lock_until": datetime_data(self.rain_lock_until),
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the episode state from plain data."""
        content = as_object(data, "active_since", "rain_lock_until")
        return cls(
            active_since=read(content, "active_since", optional(as_datetime)),
            rain_lock_until=read(content, "rain_lock_until", optional(as_datetime)),
        )


@dataclass(frozen=True, slots=True)
class SolarHeatingEpisodeState:
    """Persisted state of an active solar heating episode."""

    active_since: datetime
    opened_once: bool = False

    def __post_init__(self) -> None:
        """Reject a naive datetime."""
        object.__setattr__(
            self,
            "active_since",
            to_utc(self.active_since, "the start of the solar heating episode"),
        )
        require_type(self.opened_once, bool, "the 'opened once' flag")

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "active_since": self.active_since.isoformat(),
            "opened_once": self.opened_once,
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the episode state from plain data."""
        content = as_object(data, "active_since", "opened_once")
        return cls(
            active_since=read(content, "active_since", as_datetime),
            opened_once=read(content, "opened_once", as_bool),
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
        require_type(self.position, Position, "the position of a request")
        require_type(self.reason, str, "the reason of a request")
        object.__setattr__(
            self,
            "expires_at",
            to_utc_or_none(self.expires_at, "the expiry of a request"),
        )

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "position": self.position.value,
            "reason": self.reason,
            "expires_at": datetime_data(self.expires_at),
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the request from plain data."""
        content = as_object(data, "position", "reason", "expires_at")
        return cls(
            position=read(content, "position", _as_position),
            reason=read(content, "reason", as_str),
            expires_at=read(content, "expires_at", optional(as_datetime)),
        )


@dataclass(frozen=True, slots=True)
class LatchedDayType:
    """The day type that was determined for one date and is kept for it.

    ``fallback`` is true if the day type was fixed by the day of the week
    because a day-type input had no value until the morning trigger of the
    date had passed; the schedule keeps reporting ``day_type_fallback`` then.
    """

    day: date
    day_type: DayType
    fallback: bool = False

    def __post_init__(self) -> None:
        """Require a calendar date, not a point in time."""
        if isinstance(self.day, datetime):
            raise TypeError("a day type is latched for a date, not for a datetime")
        require_type(self.day, date, "the date of a latched day type")
        require_type(self.day_type, DayType, "the latched day type")
        require_type(self.fallback, bool, "the fallback flag of a latched day type")

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "day": self.day.isoformat(),
            "day_type": self.day_type.value,
            "fallback": self.fallback,
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the latch from plain data."""
        content = as_object(data, "day", "day_type", "fallback")
        return cls(
            day=read(content, "day", as_date),
            day_type=read(content, "day_type", as_enum(DayType)),
            fallback=read(content, "fallback", as_bool),
        )


@dataclass(frozen=True, slots=True)
class HeldInput:
    """The last known value of an on/off input that is held, and when it was seen."""

    value: bool
    seen_at: datetime

    def __post_init__(self) -> None:
        """Validate the type and reject a naive datetime."""
        require_type(self.value, bool, "the value of a held input")
        object.__setattr__(
            self,
            "seen_at",
            to_utc(self.seen_at, "the time of a held input"),
        )

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {"value": self.value, "seen_at": self.seen_at.isoformat()}

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the held input from plain data."""
        content = as_object(data, "value", "seen_at")
        return cls(
            value=read(content, "value", as_bool),
            seen_at=read(content, "seen_at", as_datetime),
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
            require_type(command, MemberCommand, "a simulated command")
        require_unique(
            (command.member_id for command in self.commands),
            "the members of the simulated commands",
        )
        object.__setattr__(
            self,
            "last_comfort_movement",
            to_utc_or_none(
                self.last_comfort_movement, "the simulated motor protection clock"
            ),
        )

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "commands": [command.to_data() for command in self.commands],
            "last_comfort_movement": datetime_data(self.last_comfort_movement),
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the simulated state from plain data."""
        content = as_object(data, "commands", "last_comfort_movement")
        return cls(
            commands=read(content, "commands", tuple_of(MemberCommand.from_data)),
            last_comfort_movement=read(
                content, "last_comfort_movement", optional(as_datetime)
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

    The brightness trigger of the evening keeps two instants:
    ``brightness_below_since`` is the time since which the outdoor brightness
    has been seen below its threshold without interruption, and
    ``evening_brightness_at`` is the instant at which it began the evening; it
    counts for the local date it lies on. Without the second one, the evening
    would end again when the brightness rises or its source drops out.
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
    brightness_below_since: datetime | None = None
    evening_brightness_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate the lists and reject naive datetimes."""
        require_type(self.owner, PositionOwner, "the owner of the position")
        object.__setattr__(self, "members", tuple(self.members))
        object.__setattr__(self, "protection_events", tuple(self.protection_events))
        object.__setattr__(self, "latched_day_types", tuple(self.latched_day_types))
        for member in self.members:
            require_type(member, MemberState, "a member state")
        require_unique(
            (member.member_id for member in self.members),
            "the members of a window state",
        )
        for event in self.protection_events:
            require_type(event, ProtectionEventState, "a protection event state")
        require_unique(
            (event.event_id for event in self.protection_events),
            "the protection events of a window state",
        )
        require_type(self.fire_unacknowledged, bool, "the fire flag")
        for name, expected in (
            ("manual_override", ManualOverrideDam),
            ("person_at_window", PersonAtWindowDam),
            ("shading_episode", ShadingEpisodeState),
            ("solar_heating_episode", SolarHeatingEpisodeState),
            ("external_request", ExternalRequest),
            ("held_frost", HeldInput),
            ("held_season", HeldInput),
            ("simulated", SimulatedState),
        ):
            require_optional_type(getattr(self, name), expected, f"the field {name!r}")
        for latch in self.latched_day_types:
            require_type(latch, LatchedDayType, "a latched day type")
        if len(self.latched_day_types) > _MAX_LATCHED_DAY_TYPES:
            raise ValueError("day types are latched for today and tomorrow only")
        require_unique(
            (latch.day.isoformat() for latch in self.latched_day_types),
            "the dates of the latched day types",
        )
        object.__setattr__(
            self,
            "last_comfort_movement",
            to_utc_or_none(
                self.last_comfort_movement, "the time of the last comfort movement"
            ),
        )
        object.__setattr__(
            self,
            "frost_waiver_until",
            to_utc_or_none(self.frost_waiver_until, "the end of the frost waiver"),
        )
        object.__setattr__(
            self,
            "brightness_below_since",
            to_utc_or_none(
                self.brightness_below_since, "the start of the low brightness"
            ),
        )
        object.__setattr__(
            self,
            "evening_brightness_at",
            to_utc_or_none(
                self.evening_brightness_at, "the evening begun by the brightness"
            ),
        )

    @property
    def commanded_targets(self) -> dict[str, Position]:
        """Return the target of the last own command of every commanded member.

        A member that was never commanded has no entry.
        """
        return {
            member.member_id: member.last_own_command.target
            for member in self.members
            if member.last_own_command is not None
        }

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
            "last_comfort_movement": datetime_data(self.last_comfort_movement),
            "held_frost": None
            if self.held_frost is None
            else self.held_frost.to_data(),
            "held_season": (
                None if self.held_season is None else self.held_season.to_data()
            ),
            "frost_waiver_until": datetime_data(self.frost_waiver_until),
            "simulated": None if self.simulated is None else self.simulated.to_data(),
            "brightness_below_since": datetime_data(self.brightness_below_since),
            "evening_brightness_at": datetime_data(self.evening_brightness_at),
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild a window state from plain data of the current schema version.

        Data of another version is refused; migrating it is the job of the
        persistence module.
        """
        content = as_object(
            data,
            "schema_version",
            "owner",
            "members",
            "manual_override",
            "person_at_window",
            "protection_events",
            "fire_unacknowledged",
            "shading_episode",
            "solar_heating_episode",
            "external_request",
            "latched_day_types",
            "last_comfort_movement",
            "held_frost",
            "held_season",
            "frost_waiver_until",
            "simulated",
            "brightness_below_since",
            "evening_brightness_at",
        )
        version = read(content, "schema_version", as_int)
        if version != WINDOW_STATE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported schema version {version}, "
                f"expected {WINDOW_STATE_SCHEMA_VERSION}"
            )
        return cls(
            owner=read(content, "owner", as_enum(PositionOwner)),
            members=read(content, "members", tuple_of(MemberState.from_data)),
            manual_override=read(
                content, "manual_override", optional(ManualOverrideDam.from_data)
            ),
            person_at_window=read(
                content, "person_at_window", optional(PersonAtWindowDam.from_data)
            ),
            protection_events=read(
                content, "protection_events", tuple_of(ProtectionEventState.from_data)
            ),
            fire_unacknowledged=read(content, "fire_unacknowledged", as_bool),
            shading_episode=read(
                content, "shading_episode", optional(ShadingEpisodeState.from_data)
            ),
            solar_heating_episode=read(
                content,
                "solar_heating_episode",
                optional(SolarHeatingEpisodeState.from_data),
            ),
            external_request=read(
                content, "external_request", optional(ExternalRequest.from_data)
            ),
            latched_day_types=read(
                content, "latched_day_types", tuple_of(LatchedDayType.from_data)
            ),
            last_comfort_movement=read(
                content, "last_comfort_movement", optional(as_datetime)
            ),
            held_frost=read(content, "held_frost", optional(HeldInput.from_data)),
            held_season=read(content, "held_season", optional(HeldInput.from_data)),
            frost_waiver_until=read(
                content, "frost_waiver_until", optional(as_datetime)
            ),
            simulated=read(content, "simulated", optional(SimulatedState.from_data)),
            brightness_below_since=read(
                content, "brightness_below_since", optional(as_datetime)
            ),
            evening_brightness_at=read(
                content, "evening_brightness_at", optional(as_datetime)
            ),
        )
