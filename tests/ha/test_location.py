"""The clock port and the sun port: the named zone, the observer, the missing module."""

import sys
from datetime import UTC, timedelta, timezone
from types import ModuleType
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.sun import get_astral_observer
from homeassistant.util import dt as dt_util

from custom_components.roller_shutter_suite import location
from custom_components.roller_shutter_suite.const import DOMAIN
from custom_components.roller_shutter_suite.location import (
    SUN_PORT_CLASS,
    SUN_PORT_MODULE,
    HomeAssistantClock,
    local_zone,
    observer_of,
    sun_port,
)
from tests.ha.runtime_kit import ZONE_NAME, FakeSun, SunFactory, local


async def test_the_clock_reports_the_named_local_zone(
    hass: HomeAssistant, freezer: Any
) -> None:
    """``now()`` is the frozen time in the zone Home Assistant is configured with."""
    await hass.config.async_set_time_zone(ZONE_NAME)
    freezer.move_to(local(10, 0))

    zone = local_zone(hass)
    now = HomeAssistantClock(zone).now()

    assert zone.key == ZONE_NAME
    assert now == local(10, 0)
    assert now.tzinfo is zone
    assert now.utcoffset() == timedelta(hours=2)
    assert now.date() == local(10, 0).date()


async def test_a_zone_without_a_name_is_refused(hass: HomeAssistant) -> None:
    """A fixed offset cannot say when its clocks change; the set-up fails closed.

    The harness restores the default zone of Home Assistant after the test.
    """
    dt_util.set_default_time_zone(timezone(timedelta(hours=2)))
    with pytest.raises(ConfigEntryError, match="not a named zone"):
        local_zone(hass)

    dt_util.set_default_time_zone(UTC)
    with pytest.raises(ConfigEntryError, match="not a named zone"):
        local_zone(hass)


async def test_the_sun_port_gets_the_plain_values(
    hass: HomeAssistant, fake_sun: SunFactory
) -> None:
    """The one implementation is built from latitude, longitude, elevation and the zone name."""
    await hass.config.async_set_time_zone(ZONE_NAME)

    port = sun_port(hass)

    assert isinstance(port, FakeSun)
    assert fake_sun.ports == [port]
    assert port.zone_name == ZONE_NAME
    assert port.latitude == hass.config.latitude
    assert port.longitude == hass.config.longitude
    assert port.elevation == hass.config.elevation


async def test_the_observer_is_taken_from_the_current_helper(
    hass: HomeAssistant,
) -> None:
    """Plain values from ``get_astral_observer`` and the name of the zone."""
    await hass.config.async_set_time_zone(ZONE_NAME)
    expected = get_astral_observer(hass)

    observer = observer_of(hass)

    assert observer.latitude == expected.latitude
    assert observer.longitude == expected.longitude
    assert observer.elevation == expected.elevation
    assert observer.zone_name == ZONE_NAME
    assert isinstance(ZoneInfo(observer.zone_name), ZoneInfo)


async def test_a_missing_sun_port_fails_the_set_up_closed(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the astral-backed port no sun time can be computed: a clear error."""
    monkeypatch.undo()  # the fake sun of the conftest is off
    monkeypatch.setitem(
        sys.modules, f"custom_components.{DOMAIN}.{SUN_PORT_MODULE}", None
    )

    with pytest.raises(ConfigEntryError, match=SUN_PORT_CLASS):
        location.astral_sun_port()


async def test_the_real_sun_port_module_is_used_when_it_exists(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The class named in the module is what the runtime builds the port from."""
    monkeypatch.undo()
    module = ModuleType(f"custom_components.{DOMAIN}.{SUN_PORT_MODULE}")
    built: list[tuple[float, float, float, str]] = []

    class AstralSun:
        def __init__(
            self, latitude: float, longitude: float, elevation: float, zone_name: str
        ) -> None:
            built.append((latitude, longitude, elevation, zone_name))

    setattr(module, SUN_PORT_CLASS, AstralSun)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    await hass.config.async_set_time_zone(ZONE_NAME)

    port = sun_port(hass)

    assert isinstance(port, AstralSun)
    assert built == [
        (hass.config.latitude, hass.config.longitude, hass.config.elevation, ZONE_NAME)
    ]

    delattr(module, SUN_PORT_CLASS)
    with pytest.raises(ConfigEntryError, match=SUN_PORT_CLASS):
        location.astral_sun_port()
