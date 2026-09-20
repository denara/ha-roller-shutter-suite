"""The resolved settings of the schedule: what a user can set, after inheritance.

Every leaf of these types is one scalar: a kind, a local time, a duration, a
number, a position or the key of a source. The settings registry can therefore
adopt them with one entry per leaf; until it does, the types below are the
definition. They are immutable, compare by value and validate themselves on
construction, so settings that exist are usable: every day has a morning
trigger and an evening trigger, and the morning comes first.

Local times (``time``) are wall-clock times in the local zone of the
installation and carry no zone of their own.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, time, timedelta
from enum import StrEnum, unique
from types import MappingProxyType
from typing import Final, Self

from custom_components.roller_shutter_suite.core.model import (
    DayType,
    Position,
    ScheduleProfile,
)

MAX_RANDOM_OFFSET: Final = timedelta(minutes=30)
"""The largest range a random offset can have."""

_ZENITH: Final = 90.0

_LEAP_YEAR: Final = 2000


@unique
class TriggerKind(StrEnum):
    """How the moment of a trigger is found."""

    FIXED_TIME = "fixed_time"
    """A local time."""
    SUN_EVENT = "sun_event"
    """Sunrise for the morning trigger, sunset for the evening trigger, with an offset."""
    ELEVATION = "elevation"
    """The sun passes an elevation: upwards in the morning, downwards in the evening."""


def _require_local_time(value: object, what: str) -> None:
    if not isinstance(value, time):
        raise TypeError(f"{what} must be a time, not {type(value).__name__}")
    if value.tzinfo is not None:
        raise ValueError(
            f"{what} is a local time of the installation and carries no zone"
        )


def _require_duration(value: object, what: str) -> None:
    if not isinstance(value, timedelta):
        raise TypeError(f"{what} must be a duration, not {type(value).__name__}")


def _require_source_key(value: object, what: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise TypeError(f"{what} must be the key of a source or None")
    if not value:
        raise ValueError(f"{what} must not be empty")


@dataclass(frozen=True, slots=True)
class Trigger:
    """One trigger of the schedule: morning or evening of one day type.

    Which fields count depends on the kind:

    - ``fixed_time``: ``at``. The clamps are optional; they matter only with a
      random offset and for the brightness trigger of the evening.
    - ``sun_event``: ``offset`` (negative = earlier), and both clamps.
    - ``elevation``: ``elevation`` in degrees, and both clamps.

    Both clamps are mandatory for the two kinds that depend on the sun: they
    are what the trigger falls on when the sun gives no moment on a day, so a
    day never lacks a trigger. A field that belongs to another kind is
    type-checked and otherwise ignored, so a user can switch the kind without
    clearing what was entered before.
    """

    kind: TriggerKind
    at: time | None = None
    offset: timedelta = timedelta(0)
    elevation: float | None = None
    not_before: time | None = None
    not_after: time | None = None

    def __post_init__(self) -> None:
        """Validate the fields and what the kind requires."""
        if not isinstance(self.kind, TriggerKind):
            raise TypeError("the kind of a trigger must be a TriggerKind")
        for name in ("at", "not_before", "not_after"):
            value = getattr(self, name)
            if value is not None:
                _require_local_time(value, f"the field {name!r} of a trigger")
        _require_duration(self.offset, "the offset of a trigger")
        if self.elevation is not None:
            self._validate_elevation(self.elevation)
        if self.kind is TriggerKind.FIXED_TIME:
            if self.at is None:
                raise ValueError("a trigger of the kind 'fixed_time' needs its time")
        elif self.not_before is None or self.not_after is None:
            raise ValueError(
                f"a trigger of the kind {self.kind.value!r} needs 'not before' and "
                "'not after'; they are its fallback when the sun gives no moment"
            )
        if self.kind is TriggerKind.ELEVATION and self.elevation is None:
            raise ValueError("a trigger of the kind 'elevation' needs its elevation")
        if self.earliest > self.latest:
            raise ValueError("'not before' must not lie after 'not after'")
        if self.kind is TriggerKind.FIXED_TIME and not (
            self.earliest <= self.fixed_time <= self.latest
        ):
            raise ValueError("a fixed time lies inside its clamps")

    @staticmethod
    def _validate_elevation(elevation: object) -> None:
        if isinstance(elevation, bool) or not isinstance(elevation, (int, float)):
            raise TypeError("the elevation of a trigger must be a number")
        if not math.isfinite(elevation) or not -_ZENITH <= elevation <= _ZENITH:
            raise ValueError("the elevation of a trigger is within -90 and 90 degrees")

    @property
    def fixed_time(self) -> time:
        """Return the local time of a fixed-time trigger."""
        if self.kind is not TriggerKind.FIXED_TIME or self.at is None:
            raise ValueError("only a trigger of the kind 'fixed_time' has a time")
        return self.at

    @property
    def earliest(self) -> time:
        """Return the earliest local time of the trigger, before a random offset."""
        if self.not_before is not None:
            return self.not_before
        return self.fixed_time

    @property
    def latest(self) -> time:
        """Return the latest local time of the trigger, before a random offset."""
        if self.not_after is not None:
            return self.not_after
        return self.fixed_time


@dataclass(frozen=True, slots=True)
class DayTriggers:
    """The morning and the evening trigger of one day type.

    The latest morning lies before the earliest evening, so every day has a
    part ``day`` and a part ``night`` in this order.
    """

    morning: Trigger
    evening: Trigger

    def __post_init__(self) -> None:
        """Validate the types and the order of the two triggers."""
        for name in ("morning", "evening"):
            if not isinstance(getattr(self, name), Trigger):
                raise TypeError(f"the {name} trigger must be a Trigger")
        if self.morning.latest >= self.evening.earliest:
            raise ValueError(
                "the latest morning trigger must lie before the earliest evening "
                "trigger"
            )


@dataclass(frozen=True, slots=True, order=True)
class DayOfYear:
    """A day of the year without a year: the first or the last day of summer."""

    month: int
    day: int

    def __post_init__(self) -> None:
        """Reject everything that is not a calendar day (29 February is one)."""
        for value in (self.month, self.day):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("month and day must be integers")
        date(_LEAP_YEAR, self.month, self.day)

    @classmethod
    def of(cls, day: date) -> Self:
        """Return the day of the year of a date."""
        return cls(day.month, day.day)


@dataclass(frozen=True, slots=True)
class ScheduleTargets:
    """The targets of the schedule under one profile key.

    ``evening_position_summer`` is the seasonal evening position; without it
    there is one evening position.
    """

    morning_position: Position
    evening_position: Position
    evening_position_summer: Position | None = None

    def __post_init__(self) -> None:
        """Validate the types."""
        for name in ("morning_position", "evening_position"):
            if not isinstance(getattr(self, name), Position):
                raise TypeError(f"the field {name!r} must be a Position")
        if self.evening_position_summer is not None and not isinstance(
            self.evening_position_summer, Position
        ):
            raise TypeError("the summer evening position must be a Position or None")

    def evening(self, *, summer: bool | None) -> Position:
        """Return the evening position; ``summer`` is ``None`` without a season."""
        if summer and self.evening_position_summer is not None:
            return self.evening_position_summer
        return self.evening_position


@dataclass(frozen=True, slots=True)
class ScheduleSettings:
    """Everything the schedule of one window is configured with.

    - ``workday``, ``weekend``, ``holiday``: the triggers per day type.
    - ``targets``: the positions, looked up through the profile key of the
      window. The key has one value, so the mapping has one entry.
    - ``workday_source`` (on = workday) and ``holiday_source`` (on = public
      holiday): keys of on/off sources, both optional.
    - ``season_source`` (on = summer), else ``summer_first_day`` and
      ``summer_last_day`` (both inclusive; the range may run across the turn
      of the year), else one evening position.
    - ``brightness_source``: key of a numeric source. The evening also begins
      when it has been below ``brightness_threshold`` for ``brightness_delay``,
      but not before "not before" of the evening trigger, which every evening
      trigger then needs.
    - ``random_offset``: the range of the random offset, 0 (off) to 30 minutes.
    """

    workday: DayTriggers
    weekend: DayTriggers
    holiday: DayTriggers
    targets: Mapping[ScheduleProfile, ScheduleTargets]
    workday_source: str | None = None
    holiday_source: str | None = None
    season_source: str | None = None
    summer_first_day: DayOfYear | None = None
    summer_last_day: DayOfYear | None = None
    brightness_source: str | None = None
    brightness_threshold: float | None = None
    brightness_delay: timedelta = timedelta(0)
    random_offset: timedelta = timedelta(0)

    def __post_init__(self) -> None:
        """Validate every part and freeze the mapping of the targets."""
        for name in ("workday", "weekend", "holiday"):
            if not isinstance(getattr(self, name), DayTriggers):
                raise TypeError(f"the triggers of the {name} must be DayTriggers")
        self._freeze_targets()
        for name in (
            "workday_source",
            "holiday_source",
            "season_source",
            "brightness_source",
        ):
            _require_source_key(getattr(self, name), f"the setting {name!r}")
        self._validate_summer()
        self._validate_brightness()
        _require_duration(self.random_offset, "the range of the random offset")
        if not timedelta(0) <= self.random_offset <= MAX_RANDOM_OFFSET:
            raise ValueError("the range of the random offset is 0 to 30 minutes")

    def _freeze_targets(self) -> None:
        targets = dict(self.targets)
        for key, value in targets.items():
            if not isinstance(key, ScheduleProfile):
                raise TypeError("the targets are keyed by a ScheduleProfile")
            if not isinstance(value, ScheduleTargets):
                raise TypeError("the targets of a profile must be ScheduleTargets")
        missing = [
            profile.value for profile in ScheduleProfile if profile not in targets
        ]
        if missing:
            raise ValueError(f"the targets lack the profile {missing[0]!r}")
        object.__setattr__(self, "targets", MappingProxyType(targets))

    def _validate_summer(self) -> None:
        for name in ("summer_first_day", "summer_last_day"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, DayOfYear):
                raise TypeError(f"the setting {name!r} must be a DayOfYear or None")
        if (self.summer_first_day is None) != (self.summer_last_day is None):
            raise ValueError("the first and the last day of summer belong together")

    def _validate_brightness(self) -> None:
        _require_duration(self.brightness_delay, "the delay of the brightness trigger")
        if self.brightness_delay < timedelta(0):
            raise ValueError("the delay of the brightness trigger must not be negative")
        threshold = self.brightness_threshold
        if threshold is not None:
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
                raise TypeError("the brightness threshold must be a number")
            if not math.isfinite(threshold):
                raise ValueError("the brightness threshold must be a finite number")
        if self.brightness_source is None:
            return
        if threshold is None:
            raise ValueError("a brightness source needs a threshold")
        for name in ("workday", "weekend", "holiday"):
            if getattr(self, name).evening.not_before is None:
                raise ValueError(
                    "with a brightness source every evening trigger needs 'not "
                    f"before'; the {name} lacks it"
                )

    def triggers_for(self, day_type: DayType) -> DayTriggers:
        """Return the triggers of a day type."""
        if day_type is DayType.HOLIDAY:
            return self.holiday
        if day_type is DayType.WEEKEND:
            return self.weekend
        return self.workday

    def targets_for(self, profile: ScheduleProfile) -> ScheduleTargets:
        """Return the targets under the profile key of a window."""
        return self.targets[profile]

    @property
    def summer_range(self) -> tuple[DayOfYear, DayOfYear] | None:
        """Return the first and the last day of summer, or ``None``."""
        if self.summer_first_day is None or self.summer_last_day is None:
            return None
        return (self.summer_first_day, self.summer_last_day)
