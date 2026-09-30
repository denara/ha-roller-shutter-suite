"""What the movement tracker keeps per member, what it measures, what it reports.

The tracker (``core/tracking``, section 8.3 of the specification) follows
every member through ``idle`` → ``expecting`` → ``moving`` → ``settling`` →
``idle``. What it has to remember across two observations, and across a
restart, is :class:`MemberTracking`. What it measures about own movements is
:class:`SelfMeasurement`. What it and the dams report are
:class:`TrackerEvent` values: codes of the group "tracker and life cycle
(events only)" with their subject as attributes, never inside the code.
"""

import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, unique
from typing import Final, Self

from custom_components.roller_shutter_suite.core.reasons import (
    ReasonCategory,
    ReasonCode,
)

from ._data import (
    JsonObject,
    JsonValue,
    as_bool,
    as_datetime,
    as_enum,
    as_int,
    as_object,
    as_str,
    datetime_data,
    optional,
    read,
    read_optional,
    tuple_of,
)
from ._validation import (
    require_identifier,
    require_optional_type,
    require_type,
    to_utc_or_none,
)
from .observation import Observation
from .values import Position, _position_data

SELF_MEASUREMENT_SAMPLES: Final = 20
"""How many samples per value the self-measurement keeps (ruling of the owner)."""


@unique
class TrackerPhase(StrEnum):
    """Where the tracker of one member stands (section 8.3)."""

    IDLE = "idle"
    """No movement is expected and none is under way."""
    EXPECTING = "expecting"
    """An own command was sent; nothing has been seen of it yet."""
    MOVING = "moving"
    """A movement is under way: the own one, or somebody else's."""
    SETTLING = "settling"
    """The member reported rest; the movement is judged after the settle time."""


@dataclass(frozen=True, slots=True)
class MemberTracking:
    """What the tracker of one member remembers between two observations.

    - ``phase``: see :class:`TrackerPhase`.
    - ``command_id``: the own command the movement is attributed to, while it
      is; ``None`` in ``idle`` and for a movement that is not the
      integration's.
    - ``external``: the movement under way is somebody else's (it started in
      ``idle``, or a reversal took it from the own command).
    - ``detected``: the external movement has been reported already (at a
      reversal, before it ended); its end only updates the remembered
      position of the dam, and no second report follows.
    - ``moved_at``: the first report of a movement (a transit state, or a
      position change): the start of the movement, and the latency of the
      self-measurement.
    - ``transit_seen``: the movement showed a transit state; a report of rest
      is then its end.
    - ``rested_at``: the report of rest that started the settle time.
    - ``before_gap``: the last available observation before the member became
      unavailable; its return is compared with it.
    - ``ended_in_gap``: a deadline ended an expectation of an own command
      while the member was away (``before_gap`` is set); only then may a
      return at the target of that command be the own movement that
      finished during the gap. Set with ``before_gap`` only.
    - ``user_hint``: a user identifier seen in the context of a report at the
      start of a foreign movement; a hint for the diagnostics that never
      decides (guardrail 6).

    All instants are kept in UTC.
    """

    phase: TrackerPhase = TrackerPhase.IDLE
    command_id: str | None = None
    external: bool = False
    detected: bool = False
    moved_at: datetime | None = None
    transit_seen: bool = False
    rested_at: datetime | None = None
    before_gap: Observation | None = None
    user_hint: str | None = None
    ended_in_gap: bool = False

    def __post_init__(self) -> None:
        """Validate the types and the combinations of the phase."""
        require_type(self.phase, TrackerPhase, "the phase of the tracker")
        if self.command_id is not None:
            require_identifier(self.command_id, "the command of the tracker")
        for name in ("external", "detected", "transit_seen", "ended_in_gap"):
            require_type(getattr(self, name), bool, f"the flag {name!r}")
        if self.ended_in_gap and self.before_gap is None:
            raise ValueError("only a gap can have ended an expectation")
        object.__setattr__(
            self, "moved_at", to_utc_or_none(self.moved_at, "the start of a movement")
        )
        object.__setattr__(
            self, "rested_at", to_utc_or_none(self.rested_at, "the rest of a movement")
        )
        require_optional_type(
            self.before_gap, Observation, "the observation before a gap"
        )
        if self.before_gap is not None and not self.before_gap.available:
            raise ValueError("the observation before a gap is an available one")
        require_optional_type(self.user_hint, str, "the user hint of a movement")
        self._validate_phase()

    def _validate_phase(self) -> None:
        if self.external and self.command_id is not None:
            raise ValueError("a movement is either an own one or somebody else's")
        if self.detected and not self.external:
            raise ValueError("only an external movement is detected")
        if self.phase is TrackerPhase.IDLE:
            if (
                self.command_id is not None
                or self.external
                or self.moved_at is not None
                or self.rested_at is not None
                or self.transit_seen
                or self.user_hint is not None
            ):
                raise ValueError("an idle tracker follows no movement")
            return
        if self.phase is TrackerPhase.EXPECTING and (
            self.command_id is None or self.moved_at is not None
        ):
            raise ValueError("an expecting tracker waits for an own command to start")
        if self.phase in (TrackerPhase.MOVING, TrackerPhase.SETTLING) and (
            self.command_id is None and not self.external
        ):
            raise ValueError("a movement belongs to an own command or to somebody else")
        if self.phase is TrackerPhase.SETTLING and self.rested_at is None:
            raise ValueError("a settling tracker knows when the member came to rest")
        if self.phase is not TrackerPhase.SETTLING and self.rested_at is not None:
            raise ValueError("only a settling tracker has a time of rest")

    @property
    def follows_own_command(self) -> bool:
        """Return whether a movement under way is attributed to an own command."""
        return self.command_id is not None

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "phase": self.phase.value,
            "command_id": self.command_id,
            "external": self.external,
            "detected": self.detected,
            "moved_at": datetime_data(self.moved_at),
            "transit_seen": self.transit_seen,
            "rested_at": datetime_data(self.rested_at),
            "before_gap": None
            if self.before_gap is None
            else self.before_gap.to_data(),
            "user_hint": self.user_hint,
            "ended_in_gap": self.ended_in_gap,
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the tracking of a member from plain data.

        ``ended_in_gap`` came with block H10 within schema version 1 and is
        optional; data without it has no expectation ended in a gap.
        """
        content = as_object(
            data,
            "phase",
            "command_id",
            "external",
            "detected",
            "moved_at",
            "transit_seen",
            "rested_at",
            "before_gap",
            "user_hint",
            "ended_in_gap",
        )
        return cls(
            phase=read(content, "phase", as_enum(TrackerPhase)),
            command_id=read(content, "command_id", optional(as_str)),
            external=read(content, "external", as_bool),
            detected=read(content, "detected", as_bool),
            moved_at=read(content, "moved_at", optional(as_datetime)),
            transit_seen=read(content, "transit_seen", as_bool),
            rested_at=read(content, "rested_at", optional(as_datetime)),
            before_gap=read(content, "before_gap", optional(Observation.from_data)),
            user_hint=read(content, "user_hint", optional(as_str)),
            ended_in_gap=read_optional(content, "ended_in_gap", as_bool, default=False),
        )


@dataclass(frozen=True, slots=True)
class SampleStatistic:
    """Count, median and maximum of the samples of one value; ``None`` without any."""

    count: int
    median: float | None
    maximum: int | None


def _statistic(samples: tuple[int, ...]) -> SampleStatistic:
    if not samples:
        return SampleStatistic(0, None, None)
    return SampleStatistic(
        len(samples), float(statistics.median(samples)), max(samples)
    )


def _samples(values: Iterable[int], what: str) -> tuple[int, ...]:
    kept = tuple(values)
    for value in kept:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"a sample of {what} is a whole number")
        if value < 0:
            raise ValueError(f"a sample of {what} is not negative")
    if len(kept) > SELF_MEASUREMENT_SAMPLES:
        raise ValueError(
            f"the self-measurement keeps at most {SELF_MEASUREMENT_SAMPLES} "
            f"samples of {what}"
        )
    return kept


@dataclass(frozen=True, slots=True)
class SelfMeasurement:
    """What the tracker measured about the own movements of one member.

    The last twenty samples per value (section 8.3; ruling of the project
    owner for block C06): the latency from the command to the first report
    and the time from the command to the report of rest, in milliseconds,
    and the deviation between the commanded and the reported end position,
    in percent. Only a member whose position is reported event-driven, with
    a report delay of zero, is measured. The statistic is the median, never
    the mean, so that one movement cut short by the overload protection of a
    motor does not distort it. Nothing is tuned from these values; they are
    for a person who looks for the right report delay and travel times.
    """

    latency_ms: tuple[int, ...] = ()
    rest_ms: tuple[int, ...] = ()
    deviation: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        """Validate and bound the samples."""
        object.__setattr__(self, "latency_ms", _samples(self.latency_ms, "latency"))
        object.__setattr__(self, "rest_ms", _samples(self.rest_ms, "time to rest"))
        object.__setattr__(self, "deviation", _samples(self.deviation, "deviation"))

    def with_sample(self, latency_ms: int, rest_ms: int, deviation: int) -> Self:
        """Return the measurement with one more movement; the oldest sample goes."""
        keep = SELF_MEASUREMENT_SAMPLES
        return type(self)(
            latency_ms=(*self.latency_ms, latency_ms)[-keep:],
            rest_ms=(*self.rest_ms, rest_ms)[-keep:],
            deviation=(*self.deviation, deviation)[-keep:],
        )

    @property
    def latency(self) -> SampleStatistic:
        """Return count, median and maximum of the latency, in milliseconds."""
        return _statistic(self.latency_ms)

    @property
    def time_to_rest(self) -> SampleStatistic:
        """Return count, median and maximum of the time to rest, in milliseconds."""
        return _statistic(self.rest_ms)

    @property
    def end_deviation(self) -> SampleStatistic:
        """Return count, median and maximum of the deviation, in percent."""
        return _statistic(self.deviation)

    def to_data(self) -> JsonObject:
        """Return plain data for persistence."""
        return {
            "latency_ms": list(self.latency_ms),
            "rest_ms": list(self.rest_ms),
            "deviation": list(self.deviation),
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the measurement from plain data."""
        content = as_object(data, "latency_ms", "rest_ms", "deviation")
        return cls(
            latency_ms=read(content, "latency_ms", tuple_of(as_int)),
            rest_ms=read(content, "rest_ms", tuple_of(as_int)),
            deviation=read(content, "deviation", tuple_of(as_int)),
        )


@dataclass(frozen=True, slots=True)
class TrackerEvent:
    """An event of the tracker or the life cycle of a window.

    ``code`` is a reason code of the group "tracker and life cycle (events
    only)". The subject is an attribute, never part of the code: the member,
    the position a person chose, the count and the threshold of the comfort
    movements, the user identifier seen at a foreign movement (a hint that
    never decides). The instant is the one of the call that raised it; the
    caller knows it. Events are not persisted: the Home Assistant layer puts
    them on the bus and into the logbook.
    """

    code: ReasonCode
    member_id: str | None = None
    position: Position | None = None
    count: int | None = None
    threshold: int | None = None
    user_id: str | None = None

    def __post_init__(self) -> None:
        """Accept event codes only; validate the attributes."""
        require_type(self.code, ReasonCode, "the code of an event")
        if self.code.category is not ReasonCategory.EVENT:
            raise ValueError(
                f"an event carries a code of the group 'event'; {self.code.value!r} "
                f"belongs to {self.code.category.value!r}"
            )
        if self.member_id is not None:
            require_identifier(self.member_id, "the member of an event")
        require_optional_type(self.position, Position, "the position of an event")
        for name in ("count", "threshold"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int)
            ):
                raise TypeError(f"the {name} of an event is a whole number")
        require_optional_type(self.user_id, str, "the user of an event")

    def to_data(self) -> JsonObject:
        """Return plain data, for the diagnostics and the event bus."""
        return {
            "code": self.code.value,
            "member_id": self.member_id,
            "position": _position_data(self.position),
            "count": self.count,
            "threshold": self.threshold,
            "user_id": self.user_id,
        }
