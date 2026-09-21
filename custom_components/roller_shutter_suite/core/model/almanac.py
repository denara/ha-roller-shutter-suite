"""The sun almanac: the answers of the sun port that a recompute may look at.

A recompute is a function of the window configuration and the world snapshot,
and it asks no port. The clock port reaches it as the time of the snapshot,
the sun port as the sun position of the snapshot and as this almanac: for a
few local dates, sunrise, sunset and the moments at which the sun passes the
elevations that the schedule of the window names. Whoever builds a snapshot asks the sun port once and writes the
answers down; ``build_sun_almanac`` of the schedule does that.

An answer of the port can be "there is none on this day" (``None``). That is
an answer and stands in the almanac. What the almanac was never asked is
missing from it, and nobody may guess it.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Self

from ._data import (
    JsonObject,
    JsonValue,
    as_bool,
    as_date,
    as_datetime,
    as_object,
    datetime_data,
    optional,
    read,
    tuple_of,
)
from ._validation import require_finite, require_type, require_unique, to_utc_or_none


def _as_number(value: JsonValue) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected a number")  # noqa: TRY004
    return float(value)


@dataclass(frozen=True, slots=True)
class ElevationPassage:
    """When the sun passes an elevation on one day: upwards or downwards.

    ``at`` is ``None`` if the sun does not pass the elevation on that day. A
    passage that was never asked for is not in the day at all
    (``SunDay.passage`` returns ``None`` for that).
    """

    elevation: float
    rising: bool
    at: datetime | None

    def __post_init__(self) -> None:
        """Validate the types and keep the instant in UTC."""
        require_finite(self.elevation, "the elevation of a passage")
        require_type(self.rising, bool, "the direction of a passage")
        object.__setattr__(self, "at", to_utc_or_none(self.at, "the time of a passage"))

    def to_data(self) -> JsonObject:
        """Return plain data."""
        return {
            "elevation": self.elevation,
            "rising": self.rising,
            "at": datetime_data(self.at),
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the passage from plain data."""
        content = as_object(data, "elevation", "rising", "at")
        return cls(
            elevation=read(content, "elevation", _as_number),
            rising=read(content, "rising", as_bool),
            at=read(content, "at", optional(as_datetime)),
        )


@dataclass(frozen=True, slots=True)
class SunDay:
    """What the sun port said about one local date.

    ``sunrise`` and ``sunset`` are ``None`` if the day has none: that is what
    the port said, and it is not the same as a day that is missing from the
    almanac (``SunAlmanac.day`` returns ``None`` for that).
    """

    day: date
    sunrise: datetime | None
    sunset: datetime | None
    passages: tuple[ElevationPassage, ...] = ()

    def __post_init__(self) -> None:
        """Validate the types and keep the instants in UTC."""
        if isinstance(self.day, datetime):
            raise TypeError("a day of the almanac is a date, not a datetime")
        require_type(self.day, date, "a day of the almanac")
        object.__setattr__(
            self, "sunrise", to_utc_or_none(self.sunrise, "a sunrise of the almanac")
        )
        object.__setattr__(
            self, "sunset", to_utc_or_none(self.sunset, "a sunset of the almanac")
        )
        object.__setattr__(self, "passages", tuple(self.passages))
        for passage in self.passages:
            require_type(passage, ElevationPassage, "a passage of the almanac")
        require_unique(
            (f"{passage.elevation!r} {passage.rising}" for passage in self.passages),
            "the passages of a day",
        )

    def passage(self, elevation: float, *, rising: bool) -> ElevationPassage | None:
        """Return the passage of an elevation, or ``None`` if it was never asked."""
        for entry in self.passages:
            if entry.elevation == elevation and entry.rising is rising:
                return entry
        return None

    def to_data(self) -> JsonObject:
        """Return plain data."""
        return {
            "day": self.day.isoformat(),
            "sunrise": datetime_data(self.sunrise),
            "sunset": datetime_data(self.sunset),
            "passages": [passage.to_data() for passage in self.passages],
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the day from plain data."""
        content = as_object(data, "day", "sunrise", "sunset", "passages")
        return cls(
            day=read(content, "day", as_date),
            sunrise=read(content, "sunrise", optional(as_datetime)),
            sunset=read(content, "sunset", optional(as_datetime)),
            passages=read(content, "passages", tuple_of(ElevationPassage.from_data)),
        )


@dataclass(frozen=True, slots=True)
class SunAlmanac:
    """The days the sun port was asked about, each local date once."""

    days: tuple[SunDay, ...] = ()

    def __post_init__(self) -> None:
        """Validate the days."""
        object.__setattr__(self, "days", tuple(self.days))
        for entry in self.days:
            require_type(entry, SunDay, "a day of the almanac")
        require_unique(
            (entry.day.isoformat() for entry in self.days), "the days of the almanac"
        )

    def day(self, on: date) -> SunDay | None:
        """Return what is known about a local date, or ``None``."""
        for entry in self.days:
            if entry.day == on:
                return entry
        return None

    def to_data(self) -> JsonObject:
        """Return plain data."""
        return {"days": [entry.to_data() for entry in self.days]}

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the almanac from plain data."""
        content = as_object(data, "days")
        return cls(days=read(content, "days", tuple_of(SunDay.from_data)))
