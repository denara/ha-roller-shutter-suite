"""The one astral-backed implementation of the core's ``Sun`` port.

The runtime of the Home Assistant layer and the time-lapse simulation both
fill their sun almanac (``build_sun_almanac`` of the core's schedule) through
:class:`AstralSun`, so a year scenario of the simulation runs with the same sun
times as the operation. It lives outside ``core/`` on purpose: the domain core
stays plain Python without a single third-party import, and this module is
the adapter between the core's port and the ``astral`` library. It imports
nothing from Home Assistant and takes plain values: latitude, longitude,
elevation above sea level, and the name of the local zone.

``astral`` is not listed as a requirement of the integration: Home Assistant
Core ships it as one of its own dependencies, and the version Home Assistant
pins is the one that applies.

:class:`AstralSun` answers the four questions of the port for one location.
The zone matters because the port is asked about local dates: "the sunrise of
22 April" means the sunrise that falls on 22 April on the clock of the
installation, and ``astral`` itself computes transits for calendar dates in
UTC.

Every datetime that goes in or comes out is timezone-aware; a naive one is
refused. Times come back in the local zone. A day without the event (the polar
night, the polar day, an elevation the sun never passes on that date) yields
``None``, which is an answer and not an error.

Refraction is included on both sides: the elevation of
:meth:`AstralSun.position` and the passages of
:meth:`AstralSun.elevation_reached` use the same correction of ``astral``, so
"the sun passes 10 degrees at 08:12" and "the elevation at 08:12 is 10
degrees" agree. Sunrise and sunset are the moments at which the upper limb of
the sun touches the horizon, as ``astral`` defines them.
"""

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from astral import Observer, SunDirection
from astral.sun import SUN_APPARENT_RADIUS, time_of_transit, zenith_and_azimuth

from .core.model import SunPosition

_MAX_LATITUDE: Final = 90.0
_MAX_LONGITUDE: Final = 180.0
_ZENITH: Final = 90.0
_FULL_CIRCLE: Final = 360.0
_HORIZON_ZENITH: Final = _ZENITH + SUN_APPARENT_RADIUS
"""The zenith angle of sunrise and sunset: the upper limb touches the horizon."""

_ONE_DAY: Final = timedelta(days=1)


def _require_finite(value: float, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{what} must be a number")
    if not math.isfinite(value):
        raise ValueError(f"{what} must be a finite number")
    return float(value)


def _require_aware(moment: datetime, what: str) -> datetime:
    if not isinstance(moment, datetime):
        raise TypeError(f"{what} must be a datetime")
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"{what} must be timezone-aware, got a naive datetime")
    return moment


def _require_date(on: date, what: str) -> date:
    if isinstance(on, datetime):
        raise TypeError(f"{what} is a local date, not a datetime")
    if not isinstance(on, date):
        raise TypeError(f"{what} must be a date")
    return on


@dataclass(frozen=True, slots=True)
class AstralSun:
    """Sun times and positions of one location, computed with ``astral``.

    - ``latitude`` and ``longitude`` in degrees, north and east positive.
    - ``elevation`` in metres above sea level; it lowers the horizon a little.
    - ``time_zone`` is the name of the local zone of the installation
      (``"Europe/Berlin"``), the zone of ``Clock.now()``. The local dates the
      port is asked about are dates of this zone, and the times it returns
      are in this zone.

    The object is immutable and holds nothing but these four values, so the
    runtime and the simulation can share one instance per installation.
    """

    latitude: float
    longitude: float
    elevation: float
    time_zone: str

    def __post_init__(self) -> None:
        """Validate the location and resolve the zone name once."""
        latitude = _require_finite(self.latitude, "the latitude")
        longitude = _require_finite(self.longitude, "the longitude")
        elevation = _require_finite(self.elevation, "the elevation")
        if not -_MAX_LATITUDE <= latitude <= _MAX_LATITUDE:
            raise ValueError("the latitude must be within -90 and 90 degrees")
        if not -_MAX_LONGITUDE <= longitude <= _MAX_LONGITUDE:
            raise ValueError("the longitude must be within -180 and 180 degrees")
        if not isinstance(self.time_zone, str) or not self.time_zone:
            raise TypeError("the time zone is the name of a zone")
        try:
            ZoneInfo(self.time_zone)
        except (ZoneInfoNotFoundError, ValueError) as err:
            raise ValueError(f"unknown time zone {self.time_zone!r}") from err
        object.__setattr__(self, "latitude", latitude)
        object.__setattr__(self, "longitude", longitude)
        object.__setattr__(self, "elevation", elevation)

    @property
    def zone(self) -> tzinfo:
        """Return the local zone; ``zoneinfo`` caches the object by name."""
        return ZoneInfo(self.time_zone)

    @property
    def _observer(self) -> Observer:
        return Observer(self.latitude, self.longitude, self.elevation)

    def position(self, at: datetime) -> SunPosition:
        """Return azimuth and elevation of the sun at an instant.

        The elevation includes the atmospheric refraction, as the passages of
        :meth:`elevation_reached` do.
        """
        instant = _require_aware(at, "the time of a sun position").astimezone(UTC)
        zenith, azimuth = zenith_and_azimuth(self._observer, instant)
        elevation = min(_ZENITH, max(-_ZENITH, _ZENITH - zenith))
        return SunPosition(azimuth=azimuth % _FULL_CIRCLE, elevation=elevation)

    def sunrise(self, on: date) -> datetime | None:
        """Return the sunrise that falls on the local date, or ``None``."""
        on = _require_date(on, "the date of a sunrise")
        return self._transit_on(on, _HORIZON_ZENITH, SunDirection.RISING)

    def sunset(self, on: date) -> datetime | None:
        """Return the sunset that falls on the local date, or ``None``."""
        on = _require_date(on, "the date of a sunset")
        return self._transit_on(on, _HORIZON_ZENITH, SunDirection.SETTING)

    def elevation_reached(
        self, on: date, elevation: float, *, rising: bool
    ) -> datetime | None:
        """Return when the sun passes the elevation on the local date, or ``None``.

        ``rising`` selects the passage upwards (morning) or downwards
        (evening). ``None`` means that the sun does not pass the elevation on
        that date: it stays below it, or above it, all day.
        """
        on = _require_date(on, "the date of a passage")
        elevation = _require_finite(elevation, "the elevation of a passage")
        if not isinstance(rising, bool):
            raise TypeError("'rising' must be a boolean")
        direction = SunDirection.RISING if rising else SunDirection.SETTING
        return self._transit_on(on, _ZENITH - elevation, direction)

    def _transit_utc(
        self, utc_day: date, zenith: float, direction: SunDirection
    ) -> datetime | None:
        """Return the transit of a zenith angle for a calendar date in UTC.

        ``astral`` raises a ``ValueError`` from the arc cosine when the sun
        does not reach the angle on that date; that is the answer "none".
        """
        try:
            transit = time_of_transit(self._observer, utc_day, zenith, direction)
        except ValueError:
            return None
        return transit.astimezone(self.zone)

    def _transit_on(
        self, on: date, zenith: float, direction: SunDirection
    ) -> datetime | None:
        """Return the transit that falls on the local date ``on``.

        ``astral`` computes a transit for a calendar date in UTC. The transit
        that falls on a local date can belong to the UTC date before or after
        it, depending on the zone and the longitude, so up to three UTC dates
        are tried: the date itself first, because that is the usual case and
        its transit is then the answer, and the two neighbours only if it
        does not fit; of those the earlier one that fits is the answer.
        """
        found = self._transit_utc(on, zenith, direction)
        if found is not None and found.date() == on:
            return found
        candidates = [
            transit
            for utc_day in (on - _ONE_DAY, on + _ONE_DAY)
            if (transit := self._transit_utc(utc_day, zenith, direction)) is not None
            and transit.date() == on
        ]
        return min(candidates, default=None)
