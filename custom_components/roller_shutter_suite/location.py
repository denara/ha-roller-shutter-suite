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
``sun_astral.py`` of this integration. This module only obtains the
observer of the installation (latitude, longitude, elevation) through Home
Assistant's current helper and hands plain values to it, together with the
name of the local zone. Nothing here depends on the ``sun`` entity.
"""

import importlib
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Protocol
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.sun import get_astral_observer
from homeassistant.util import dt as dt_util

from .core.ports import Sun


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
    deprecated). Only plain values leave this function.
    """
    observer = get_astral_observer(hass)
    return Observer(
        latitude=float(observer.latitude),
        longitude=float(observer.longitude),
        elevation=float(observer.elevation),
        zone_name=local_zone(hass).key,
    )


class SunPortFactory(Protocol):
    """Builds the sun port from the observer of the installation."""

    def __call__(
        self, latitude: float, longitude: float, elevation: float, zone_name: str
    ) -> Sun:
        """Return the sun port for the given location and named zone."""


SUN_PORT_MODULE = "sun_astral"
"""The module of this integration that holds the astral-backed sun port."""

SUN_PORT_CLASS = "AstralSun"
"""Its class: built from latitude, longitude, elevation and a zone name."""


def astral_sun_port() -> SunPortFactory:
    """Return the one astral-backed implementation of the sun port.

    The module is resolved here and nowhere else, by name, so that the
    runtime and its tests do not depend on it at import time. An
    installation whose integration lacks it cannot compute a single sun
    time, and the set-up fails closed with a clear error instead of running
    a schedule without sun data.
    """
    try:
        module = importlib.import_module(f".{SUN_PORT_MODULE}", __package__)
        factory: SunPortFactory = getattr(module, SUN_PORT_CLASS)
    except (ImportError, AttributeError) as error:
        raise ConfigEntryError(
            f"the sun port {SUN_PORT_MODULE}.{SUN_PORT_CLASS} of the integration "
            "is missing; sun times cannot be computed"
        ) from error
    return factory


def sun_port(hass: HomeAssistant) -> Sun:
    """Return the sun port of the installation."""
    observer = observer_of(hass)
    return astral_sun_port()(
        observer.latitude, observer.longitude, observer.elevation, observer.zone_name
    )
