"""The settings of the schedule as values: triggers, targets, and their rules.

``WindowConfig`` carries every setting of the schedule as a flat field, so
that each can be inherited on its own; ``WindowConfig.schedule`` is the view
over them, a :class:`ScheduleSettings`. The types here hold the value rules of
single settings. The two rules that span several settings are functions of
this module; ``WindowConfig`` raises them with the names of its fields, and
``ScheduleSettings`` refuses a combination that violates them.

Local times (``time``) are wall-clock times in the local zone of the
installation and carry no zone of their own.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, time, timedelta
from enum import StrEnum, unique
from types import MappingProxyType
from typing import Final

from ._validation import require_type
from .values import Position

MAX_RANDOM_OFFSET: Final = timedelta(minutes=30)
"""The largest range a random offset can have."""

MAX_SUN_OFFSET_MINUTES: Final = 720
"""How far a trigger can lie before or after sunrise or sunset, in minutes."""

_ZENITH: Final = 90.0

_YEAR_WITHOUT_LEAP_DAY: Final = 2001

type _LocalTime = time
"""A wall-clock time; the name keeps the field ``time`` of a trigger apart."""


@unique
class ScheduleProfile(StrEnum):
    """The key under which the schedule looks up its targets.

    It has one value. The key exists so that an absence profile or named
    profiles can be added without restructuring.
    """

    DEFAULT = "default"


@unique
class TriggerKind(StrEnum):
    """How the moment of a trigger is found."""

    FIXED_TIME = "fixed_time"
    """A local time."""
    SUN_EVENT = "sun_event"
    """Sunrise for the morning trigger, sunset for the evening trigger, with an offset."""
    ELEVATION = "elevation"
    """The sun passes an elevation: upwards in the morning, downwards in the evening."""


TRIGGER_FIELDS: Final = (
    "kind",
    "time",
    "offset_minutes",
    "elevation",
    "not_before",
    "not_after",
)
"""The fields of a trigger, which are also the endings of its flat settings."""


class ScheduleRuleError(ValueError):
    """Settings of the schedule that are fine one by one contradict each other.

    ``fields`` names the settings the violated rule concerns, without the
    prefix of the schedule (``workday_morning_not_before`` …). ``WindowConfig``
    turns it into a ``SettingsCombinationError`` with the names of its fields.
    """

    def __init__(self, message: str, fields: tuple[str, ...]) -> None:
        """Keep the message and the fields the rule concerns."""
        super().__init__(f"{message} ({', '.join(fields)})")
        self.fields = fields


def _require_local_time(value: object, what: str) -> None:
    if not isinstance(value, time):
        raise TypeError(f"{what} must be a time, not {type(value).__name__}")
    if value.tzinfo is not None:
        raise ValueError(
            f"{what} is a local time of the installation and carries no zone"
        )


def _require_source_key(value: object, what: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise TypeError(f"{what} must be the key of a source or None")
    if not value:
        raise ValueError(f"{what} must not be empty")


def _require_number(value: object, what: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{what} must be a number")
    if not math.isfinite(value):
        raise ValueError(f"{what} must be a finite number")


@dataclass(frozen=True, slots=True)
class Trigger:
    """One trigger of the schedule: morning or evening of one day type.

    Every field always has a value; which of them count depends on the kind:

    - ``fixed_time``: ``time``.
    - ``sun_event``: ``offset_minutes`` (negative = earlier), clamped by
      ``not_before`` and ``not_after``.
    - ``elevation``: ``elevation`` in degrees, clamped the same way.

    The clamps are what a trigger of the sun falls on when the sun gives no
    moment on a day, so a day never lacks a trigger. A fixed time ignores
    them (:attr:`clamps_apply`). A field that belongs to another kind is
    checked on its own and otherwise ignored, so a user can switch the kind
    without clearing what was entered before.
    """

    kind: TriggerKind
    time: _LocalTime
    not_before: _LocalTime
    not_after: _LocalTime
    offset_minutes: int = 0
    elevation: float = 0.0

    def __post_init__(self) -> None:
        """Validate every field on its own."""
        require_type(self.kind, TriggerKind, "the kind of a trigger")
        for name in ("time", "not_before", "not_after"):
            _require_local_time(getattr(self, name), f"the field {name!r} of a trigger")
        if isinstance(self.offset_minutes, bool) or not isinstance(
            self.offset_minutes, int
        ):
            raise TypeError("the offset of a trigger is a whole number of minutes")
        if abs(self.offset_minutes) > MAX_SUN_OFFSET_MINUTES:
            raise ValueError("the offset of a trigger is within -720 and 720 minutes")
        _require_number(self.elevation, "the elevation of a trigger")
        if not -_ZENITH <= self.elevation <= _ZENITH:
            raise ValueError("the elevation of a trigger is within -90 and 90 degrees")

    @property
    def clamps_apply(self) -> bool:
        """Return whether "not before" and "not after" limit this trigger.

        They limit the kinds that depend on the sun. This is the one place
        that says so.
        """
        return self.kind is not TriggerKind.FIXED_TIME

    @property
    def offset(self) -> timedelta:
        """Return the offset to sunrise or sunset as a duration."""
        return timedelta(minutes=self.offset_minutes)

    @property
    def earliest(self) -> _LocalTime:
        """Return the earliest local time of the trigger, before a random offset."""
        return self.not_before if self.clamps_apply else self.time

    @property
    def latest(self) -> _LocalTime:
        """Return the latest local time of the trigger, before a random offset."""
        return self.not_after if self.clamps_apply else self.time

    @property
    def clamps_in_disorder(self) -> tuple[str, ...]:
        """Return the fields of the rule "not before" is not after "not after".

        Empty if the rule holds. It is a rule over several settings.
        """
        if self.clamps_apply and self.not_before > self.not_after:
            return ("kind", "not_before", "not_after")
        return ()


@dataclass(frozen=True, slots=True)
class DayTriggers:
    """The morning and the evening trigger of one day type."""

    morning: Trigger
    evening: Trigger

    def __post_init__(self) -> None:
        """Validate the types."""
        require_type(self.morning, Trigger, "the morning trigger")
        require_type(self.evening, Trigger, "the evening trigger")

    @property
    def morning_not_before_evening(self) -> tuple[str, ...]:
        """Return the fields of the rule "the latest morning lies before the earliest evening".

        Empty if the rule holds; otherwise the fields it concerns, each with
        its edge in front (``morning_time``, ``evening_not_before`` …). With
        the rule every day has a part ``day`` and a part ``night``, in this
        order. It is a rule over several settings.
        """
        if self.morning.latest < self.evening.earliest:
            return ()
        morning = "not_after" if self.morning.clamps_apply else "time"
        evening = "not_before" if self.evening.clamps_apply else "time"
        return (
            "morning_kind",
            f"morning_{morning}",
            "evening_kind",
            f"evening_{evening}",
        )


@dataclass(frozen=True, slots=True)
class ScheduleTargets:
    """The targets of the schedule under one profile key."""

    morning_position: Position
    evening_position: Position
    evening_position_summer: Position

    def __post_init__(self) -> None:
        """Validate the types."""
        for name in (
            "morning_position",
            "evening_position",
            "evening_position_summer",
        ):
            require_type(getattr(self, name), Position, f"the field {name!r}")

    def evening(self, *, summer: bool | None) -> Position:
        """Return the evening position; ``summer`` is ``None`` without a season."""
        return self.evening_position_summer if summer else self.evening_position


def require_day_of_year(value: object, what: str) -> None:
    """Refuse everything that is not (month, day) of a day that exists every year."""
    if (
        not isinstance(value, tuple)
        or len(value) != 2  # noqa: PLR2004 - a month and a day
        or any(isinstance(part, bool) or not isinstance(part, int) for part in value)
    ):
        raise TypeError(f"{what} must be a month and a day, two whole numbers")
    try:
        date(_YEAR_WITHOUT_LEAP_DAY, value[0], value[1])
    except ValueError as err:
        raise ValueError(f"{what} must be a day that exists in every year") from err


@dataclass(frozen=True, slots=True)
class ScheduleSettings:
    """Everything the schedule of one window is configured with.

    - ``enabled``: the switch of the feature.
    - ``workday``, ``weekend``, ``holiday``: the triggers per day type.
    - ``targets``: the positions, looked up through the profile key of the
      window. The key has one value, so the mapping has one entry.
    - ``workday_source`` (on = workday) and ``holiday_source`` (on = public
      holiday): keys of on/off sources, both optional.
    - ``season_source`` (on = summer); else, with ``summer_by_date``, the
      range from ``summer_first_day`` to ``summer_last_day`` (month and day,
      both inclusive; it may run across the turn of the year); else there is
      one evening position.
    - ``brightness_source``: key of a numeric source. The evening also begins
      when it has been below ``brightness_threshold`` for ``brightness_delay``,
      but not before "not before" of the evening trigger, whatever its kind.
    - ``random_offset``: the range of the random offset, 0 (off) to 30 minutes.
    """

    enabled: bool
    workday: DayTriggers
    weekend: DayTriggers
    holiday: DayTriggers
    targets: Mapping[ScheduleProfile, ScheduleTargets]
    summer_first_day: tuple[int, int]
    summer_last_day: tuple[int, int]
    brightness_threshold: float
    brightness_delay: timedelta
    workday_source: str | None = None
    holiday_source: str | None = None
    season_source: str | None = None
    summer_by_date: bool = False
    brightness_source: str | None = None
    random_offset: timedelta = timedelta(0)

    def __post_init__(self) -> None:
        """Validate every part, then the rules over several of them."""
        require_type(self.enabled, bool, "the switch of the schedule")
        for name in ("workday", "weekend", "holiday"):
            require_type(
                getattr(self, name), DayTriggers, f"the triggers of the {name}"
            )
        self._freeze_targets()
        for name in (
            "workday_source",
            "holiday_source",
            "season_source",
            "brightness_source",
        ):
            _require_source_key(getattr(self, name), f"the setting {name!r}")
        require_type(self.summer_by_date, bool, "the switch 'summer by date'")
        require_day_of_year(self.summer_first_day, "the first day of summer")
        require_day_of_year(self.summer_last_day, "the last day of summer")
        _require_number(self.brightness_threshold, "the brightness threshold")
        require_type(self.brightness_delay, timedelta, "the delay of the brightness")
        if self.brightness_delay < timedelta(0):
            raise ValueError("the delay of the brightness trigger must not be negative")
        require_type(self.random_offset, timedelta, "the range of the random offset")
        if not timedelta(0) <= self.random_offset <= MAX_RANDOM_OFFSET:
            raise ValueError("the range of the random offset is 0 to 30 minutes")
        violated = self.violated_rules
        if violated:
            raise ScheduleRuleError(*violated[0])

    def _freeze_targets(self) -> None:
        targets = dict(self.targets)
        for key, value in targets.items():
            require_type(key, ScheduleProfile, "the key of the targets")
            require_type(value, ScheduleTargets, "the targets of a profile")
        missing = [
            profile.value for profile in ScheduleProfile if profile not in targets
        ]
        if missing:
            raise ValueError(f"the targets lack the profile {missing[0]!r}")
        object.__setattr__(self, "targets", MappingProxyType(targets))

    @property
    def violated_rules(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Return the violated rules over several settings: message and fields.

        A field is named as the flat setting without the prefix of the
        schedule: ``workday_morning_not_before`` and so on.
        """
        found: list[tuple[str, tuple[str, ...]]] = []
        for name in ("workday", "weekend", "holiday"):
            day: DayTriggers = getattr(self, name)
            for edge, trigger in (("morning", day.morning), ("evening", day.evening)):
                fields = trigger.clamps_in_disorder
                if fields:
                    found.append(
                        (
                            "'not before' must not lie after 'not after'",
                            tuple(f"{name}_{edge}_{field}" for field in fields),
                        )
                    )
        for name in ("workday", "weekend", "holiday"):
            fields = getattr(self, name).morning_not_before_evening
            if fields:
                found.append(
                    (
                        "the latest morning trigger must lie before the earliest "
                        "evening trigger",
                        tuple(f"{name}_{field}" for field in fields),
                    )
                )
        return tuple(found)

    def triggers_for(self, day_type: str) -> DayTriggers:
        """Return the triggers of a day type (``DayType`` or its value)."""
        if day_type == "holiday":
            return self.holiday
        if day_type == "weekend":
            return self.weekend
        return self.workday

    def targets_for(self, profile: ScheduleProfile) -> ScheduleTargets:
        """Return the targets under the profile key of a window."""
        return self.targets[profile]

    @property
    def summer_range(self) -> tuple[tuple[int, int], tuple[int, int]] | None:
        """Return the first and the last day of summer, or ``None`` without dates."""
        if not self.summer_by_date:
            return None
        return (self.summer_first_day, self.summer_last_day)
