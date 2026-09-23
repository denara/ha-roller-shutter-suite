"""The clock port and the sun port: the named zone, the observer, the astral sun."""

from datetime import UTC, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.sun import get_astral_observer
from homeassistant.util import dt as dt_util

from custom_components.roller_shutter_suite import location
from custom_components.roller_shutter_suite.location import (
    HomeAssistantClock,
    local_zone,
    observer_of,
    sun_port,
)
from custom_components.roller_shutter_suite.sun_astral import AstralSun
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


async def test_an_elevation_that_is_not_a_height_is_refused(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``astral`` accepts a pair as elevation; the runtime takes only a height."""
    await hass.config.async_set_time_zone(ZONE_NAME)
    observer = get_astral_observer(hass)
    observer.elevation = (10.0, 100.0)
    monkeypatch.setattr(location, "get_astral_observer", lambda _hass: observer)

    with pytest.raises(ConfigEntryError, match="not a height"):
        observer_of(hass)


async def test_without_the_fake_the_sun_port_is_the_astral_one(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unpatched, the runtime builds ``AstralSun`` from the observer and the zone."""
    monkeypatch.undo()  # the fake sun of the conftest is off
    await hass.config.async_set_time_zone(ZONE_NAME)

    port = sun_port(hass)

    assert isinstance(port, AstralSun)
    assert port == AstralSun(
        hass.config.latitude, hass.config.longitude, hass.config.elevation, ZONE_NAME
    )
