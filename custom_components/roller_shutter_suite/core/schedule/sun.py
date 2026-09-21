"""Where the schedule gets sun times from: the sun port, or the almanac.

The schedule asks four questions about a local date: sunrise, sunset, the
passage of an elevation, and the elevation at local noon. :class:`PortSun`
answers them from the sun port, for the builder of the almanac and for the
simulation. :class:`AlmanacSun` answers them from the almanac of a world
snapshot, which is how a recompute gets them, because a recompute asks no
port. The almanac is filled through ``PortSun``, so both give the same
answers.

Two things must not be confused. "The sun does not rise on this date" (or
does not set, or never passes the elevation) is an **answer**: the port
returns no time, the almanac records that, and a clamp of the trigger
decides; the elevation at noon says which one. A date or a passage that is
**not in the almanac** is missing data:
:class:`ScheduleInputMissingError` says what is missing, and nothing is
guessed.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Final, Protocol

from custom_components.roller_shutter_suite.core.model import (
    ElevationPassage,
    ScheduleSettings,
    SunAlmanac,
    SunDay,
    TriggerKind,
    WindowConfig,
)
from custom_components.roller_shutter_suite.core.ports import Sun

from .local_time import as_instant, local_instant, zone_of

_NOON: Final = time(12, 0)

ALMANAC_DAYS_BEFORE: Final = 1
"""The almanac begins yesterday: before today's morning trigger, the night
that is running began with yesterday's evening trigger."""

ALMANAC_DAYS_AHEAD: Final = 7
"""The almanac ends seven days ahead: the next planned action is searched on
today and the seven dates after it, a week and a day, so that a day type
whose triggers leave no part "day" cannot hide the next action."""


class ScheduleInputMissingError(LookupError):
    """The schedule lacks an input that nobody may guess: sun data or the seed."""


class SunSource(Protocol):
    """The four questions the schedule asks about the sun on a local date."""

    def sunrise(self, on: date) -> datetime | None:
        """Return the sunrise of the date as an instant in UTC, or ``None``."""

    def sunset(self, on: date) -> datetime | None:
        """Return the sunset of the date as an instant in UTC, or ``None``."""

    def elevation_reached(
        self, on: date, elevation: float, *, rising: bool
    ) -> datetime | None:
        """Return when the sun passes the elevation, in UTC, or ``None``."""

    def noon_elevation(self, on: date) -> float:
        """Return the elevation of the sun at 12:00 local time."""


def _instant_or_none(moment: datetime | None) -> datetime | None:
    return None if moment is None else as_instant(moment, "a time of the sun port")


@dataclass(frozen=True, slots=True)
class PortSun:
    """The answers of the sun port; ``zone`` is the local zone."""

    port: Sun
    zone: tzinfo

    def sunrise(self, on: date) -> datetime | None:
        """Ask the port."""
        return _instant_or_none(self.port.sunrise(on))

    def sunset(self, on: date) -> datetime | None:
        """Ask the port."""
        return _instant_or_none(self.port.sunset(on))

    def elevation_reached(
        self, on: date, elevation: float, *, rising: bool
    ) -> datetime | None:
        """Ask the port."""
        return _instant_or_none(
            self.port.elevation_reached(on, elevation, rising=rising)
        )

    def noon_elevation(self, on: date) -> float:
        """Ask the port for the position at local noon."""
        return self.port.position(local_instant(on, _NOON, self.zone)).elevation


@dataclass(frozen=True, slots=True)
class AlmanacSun:
    """The answers that stand in an almanac; anything else is missing."""

    almanac: SunAlmanac

    def _day(self, on: date) -> SunDay:
        found = self.almanac.day(on)
        if found is None:
            raise ScheduleInputMissingError(f"the almanac has no entry for {on}")
        return found

    def sunrise(self, on: date) -> datetime | None:
        """Look the sunrise up."""
        return self._day(on).sunrise

    def sunset(self, on: date) -> datetime | None:
        """Look the sunset up."""
        return self._day(on).sunset

    def elevation_reached(
        self, on: date, elevation: float, *, rising: bool
    ) -> datetime | None:
        """Look the passage up; one that was never asked is missing."""
        passage = self._day(on).passage(elevation, rising=rising)
        if passage is None:
            raise ScheduleInputMissingError(
                f"the almanac does not say when the sun passes {elevation} on {on}"
            )
        return passage.at

    def noon_elevation(self, on: date) -> float:
        """Look the elevation at noon up."""
        return self._day(on).noon_elevation


def _named_elevations(settings: ScheduleSettings) -> tuple[tuple[float, bool], ...]:
    """Return the elevations that elevation triggers name, with their direction."""
    found: list[tuple[float, bool]] = []
    for day in (settings.workday, settings.weekend, settings.holiday):
        for trigger, rising in ((day.morning, True), (day.evening, False)):
            entry = (float(trigger.elevation), rising)
            if trigger.kind is TriggerKind.ELEVATION and entry not in found:
                found.append(entry)
    return tuple(found)


def build_sun_almanac(config: WindowConfig, at: datetime, sun: Sun) -> SunAlmanac:
    """Ask the sun port everything the schedule of this window can need at ``at``.

    From yesterday to seven days ahead (see the two constants), for every
    local date: sunrise, sunset, the elevation at local noon, and the passage
    of every elevation that an elevation trigger of the window names. "None
    on this date" is recorded as such. The
    zone of ``at`` is the local zone. Whoever builds a world snapshot calls
    this and puts the result into the snapshot; it has to be built again when
    the date or the settings of the schedule change.
    """
    source = PortSun(sun, zone_of(at))
    elevations = _named_elevations(config.schedule)
    days = []
    for ahead in range(-ALMANAC_DAYS_BEFORE, ALMANAC_DAYS_AHEAD + 1):
        on = at.date() + timedelta(days=ahead)
        days.append(
            SunDay(
                day=on,
                sunrise=source.sunrise(on),
                sunset=source.sunset(on),
                noon_elevation=source.noon_elevation(on),
                passages=tuple(
                    ElevationPassage(
                        elevation,
                        rising,
                        source.elevation_reached(on, elevation, rising=rising),
                    )
                    for elevation, rising in elevations
                ),
            )
        )
    return SunAlmanac(tuple(days))
