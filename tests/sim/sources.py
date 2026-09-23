"""Sources that follow scripted or generated time series.

A :class:`Series` is a sorted list of steps: from an instant on, the source
has a value, is unknown, or is unavailable, until the next step. Before the
first step it is unavailable, because a source that has not reported yet has
no value, and nothing turns that into a default. A :class:`Script` holds the
series of all sources of a world by their key; the runner asks it for the
values at the time of a snapshot and for the next instant at which any of them
changes, which is when the windows are recomputed.

A generated series is a scripted one whose steps a function computed: a daily
temperature curve, the brightness from the elevation of the sun, rain drawn
from a seeded random generator. The generator runs once, when the series is
built, so a run is reproducible: same scenario and seed, same steps.
"""

import bisect
import itertools
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum, unique
from typing import Final

from custom_components.roller_shutter_suite.core.model import (
    AnySourceValue,
    SourceScalar,
    SourceValue,
)


@unique
class Missing(Enum):
    """The two states of a source without a value."""

    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


type Scripted = SourceScalar | Missing
"""What a step of a series states: a value, or one of the two missing states."""

UNKNOWN: Final = Missing.UNKNOWN
UNAVAILABLE: Final = Missing.UNAVAILABLE


def _instant(moment: datetime, what: str) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"{what} must be timezone-aware")
    return moment.astimezone(UTC)


def as_source_value(scripted: Scripted) -> AnySourceValue:
    """Turn what a step states into a source value of the core."""
    if scripted is Missing.UNKNOWN:
        return SourceValue.unknown()
    if scripted is Missing.UNAVAILABLE:
        return SourceValue.unavailable()
    if isinstance(scripted, bool):
        return SourceValue.of(scripted)
    if isinstance(scripted, int):
        return SourceValue.of(scripted)
    if isinstance(scripted, float):
        return SourceValue.of(scripted)
    return SourceValue.of(scripted)


@dataclass(frozen=True, slots=True)
class Step:
    """From ``at`` on the source states ``value``."""

    at: datetime
    value: Scripted

    def __post_init__(self) -> None:
        """Keep the instant in UTC."""
        object.__setattr__(self, "at", _instant(self.at, "the time of a step"))


@dataclass(frozen=True, slots=True)
class Series:
    """The steps of one source, sorted by time; unavailable before the first."""

    steps: tuple[Step, ...] = ()
    _times: tuple[datetime, ...] = field(
        init=False, default=(), compare=False, repr=False
    )

    def __post_init__(self) -> None:
        """Sort the steps; two steps at one instant are refused."""
        steps = tuple(sorted(self.steps, key=lambda step: step.at))
        for earlier, later in itertools.pairwise(steps):
            if earlier.at == later.at:
                raise ValueError("a series states one value per instant")
        object.__setattr__(self, "steps", steps)
        object.__setattr__(self, "_times", tuple(step.at for step in steps))

    @classmethod
    def constant(cls, value: Scripted, since: datetime) -> Series:
        """Return a series with one value from an instant on."""
        return cls((Step(since, value),))

    @classmethod
    def of(cls, *steps: tuple[datetime, Scripted]) -> Series:
        """Return a series from ``(instant, value)`` pairs."""
        return cls(tuple(Step(at, value) for at, value in steps))

    @classmethod
    def generated(
        cls,
        start: datetime,
        end: datetime,
        step: timedelta,
        value_at: Callable[[datetime], Scripted],
    ) -> Series:
        """Return a series computed by a function, one step per interval.

        Steps whose value equals the previous one are left out, so a slowly
        changing curve does not wake the windows up needlessly. The function
        receives instants in UTC.
        """
        if step <= timedelta(0):
            raise ValueError("the step of a generated series is longer than zero")
        steps: list[Step] = []
        at = _instant(start, "the start of a generated series")
        until = _instant(end, "the end of a generated series")
        last: Scripted | None = None
        while at <= until:
            value = value_at(at)
            if not steps or value != last:
                steps.append(Step(at, value))
                last = value
            at += step
        return cls(tuple(steps))

    def value_at(self, moment: datetime) -> Scripted:
        """Return what the source states at an instant."""
        at = _instant(moment, "the time of a lookup")
        index = bisect.bisect_right(self._times, at)
        if index == 0:
            return Missing.UNAVAILABLE
        return self.steps[index - 1].value

    def next_change_after(self, moment: datetime) -> datetime | None:
        """Return the first step strictly after an instant, or ``None``."""
        at = _instant(moment, "the time of a lookup")
        index = bisect.bisect_right(self._times, at)
        if index >= len(self.steps):
            return None
        return self.steps[index].at


@dataclass(frozen=True, slots=True)
class Script:
    """The series of all sources of a world, by key."""

    series: Mapping[str, Series]

    def __post_init__(self) -> None:
        """Copy the mapping."""
        object.__setattr__(self, "series", dict(self.series))

    @classmethod
    def empty(cls) -> Script:
        """Return a script without sources."""
        return cls({})

    def with_series(self, key: str, series: Series) -> Script:
        """Return the script with one series added or replaced."""
        return Script({**self.series, key: series})

    def values_at(self, moment: datetime) -> dict[str, AnySourceValue]:
        """Return every source as a source value at an instant."""
        return {
            key: as_source_value(series.value_at(moment))
            for key, series in self.series.items()
        }

    def next_change_after(self, moment: datetime) -> datetime | None:
        """Return the earliest step of any series strictly after an instant."""
        changes = [
            change
            for series in self.series.values()
            if (change := series.next_change_after(moment)) is not None
        ]
        return min(changes, default=None)

    def keys(self) -> Iterable[str]:
        """Return the keys of the sources."""
        return self.series.keys()
