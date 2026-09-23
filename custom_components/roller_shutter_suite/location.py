"""Where and when the installation is: the clock port and the sun port.

**The clock.** ``HomeAssistantClock.now()`` is the current time in the
**named** local zone of the installation, the zone Home Assistant was
configured with. The core reads everything local from that zone: fixed
times of the schedule, local midnight, the local dates it hands to the sun
port. A time in UTC or with a fixed offset would put every local time into
the wrong zone or lose the rule for clock changes, so a zone that is not a
named one is refused at set-up.

**The sun.** The core computes nothing astronomical; it gets sun times and
sun positions through its ``Sun`` port. There is exactly one implementation
of that port, backed by the ``astral`` library that Home Assistant ships, in
``sun_astral.py`` of this integration, which this module imports like any
other module of the integration. This module only obtains the
observer of the installation (latitude, longitude, elevation) through Home
Assistant's current helper and hands plain values to it, together with the
name of the local zone. Nothing here depends on the ``sun`` entity.
"""

from dataclasses import dataclass
from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.sun import get_astral_observer
from homeassistant.util import dt as dt_util

from .core.ports import Sun
from .sun_astral import AstralSun


def local_zone(hass: HomeAssistant) -> ZoneInfo:
    """Return the named local zone of the installation.

    It is the zone Home Assistant uses for local times (``dt_util.now()``),
    set from the configured time zone. A zone without a name (a fixed
    offset, for example) cannot say when its clocks change, so it is refused.
    """
    zone = dt_util.get_default_time_zone()
    if not isinstance(zone, ZoneInfo) or not zone.key:
        raise ConfigEntryError(
            f"the time zone of Home Assistant is not a named zone ({zone!r})"
        )
    return zone


@dataclass(frozen=True, slots=True)
class HomeAssistantClock:
    """The clock port: the current time in the named local zone."""

    zone: tzinfo

    def now(self) -> datetime:
        """Return the current time in the local zone of the installation."""
        return dt_util.utcnow().astimezone(self.zone)


@dataclass(frozen=True, slots=True)
class Observer:
    """The location of the installation as plain values, and its zone by name."""

    latitude: float
    longitude: float
    elevation: float
    zone_name: str


def observer_of(hass: HomeAssistant) -> Observer:
    """Return the observer of the installation from Home Assistant's helper.

    ``homeassistant.helpers.sun.get_astral_observer`` is the current helper
    (Core 2026.9.2: it returns ``astral.Observer(latitude, longitude,
    elevation)`` from the configuration; ``get_astral_location`` is
    deprecated). Only plain values leave this function. ``astral`` also
    knows an elevation given as a pair (a height and the distance to an
    obscuring feature); Home Assistant configures a height in metres, and
    anything else fails the set-up closed instead of being guessed at.
    """
    observer = get_astral_observer(hass)
    elevation = observer.elevation
    if isinstance(elevation, tuple):
        raise ConfigEntryError(
            "the elevation of the installation is not a height in metres"
        )
    return Observer(
        latitude=float(observer.latitude),
        longitude=float(observer.longitude),
        elevation=float(elevation),
        zone_name=local_zone(hass).key,
    )


def sun_port(hass: HomeAssistant) -> Sun:
    """Return the sun port of the installation: the astral-backed one.

    ``AstralSun`` is imported at the top of this module, so it is loaded
    with the integration's modules, which Home Assistant imports outside the
    event loop. Nothing is imported while the loop runs.
    """
    observer = observer_of(hass)
    return AstralSun(
        observer.latitude, observer.longitude, observer.elevation, observer.zone_name
    )
