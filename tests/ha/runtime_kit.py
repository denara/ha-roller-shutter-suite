"""What the tests of the runtime share: an invented sun, a window, controlled time.

The sun port of the integration is built by ``location.sun_port`` from the
astral-backed implementation. The tests replace that implementation with
:class:`FakeSun`, which answers with fixed local times in the named zone the
runtime hands it, so every sun time is known by heart and no astronomy runs.
The fixture ``fake_sun`` in ``conftest.py`` puts it into effect for every
test; ``fake_sun.ports`` lists the ports that were built, with the plain
values the runtime handed in.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.components.cover import ATTR_POSITION
from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    SERVICE_SET_COVER_POSITION,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.util import dt as dt_util
from homeassistant.util.hass_dict import HassKey
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.roller_shutter_suite.const import (
    CONF_COVERS,
    CONF_DRY_RUN,
    CONF_SETTINGS,
    SUBENTRY_WINDOW,
)
from custom_components.roller_shutter_suite.controller import Phase, WindowController
from custom_components.roller_shutter_suite.core.model import Position, SunPosition
from custom_components.roller_shutter_suite.core.schedule import ScheduleResult
from custom_components.roller_shutter_suite.runtime import SuiteRuntime
from tests.ha.helpers import set_cover, setup_entry, subentry_data

ZONE_NAME = "Europe/Berlin"
"""A named zone with daylight saving time; in 2026 its clocks go forward on
29 March (02:00 becomes 03:00) and back on 25 October (03:00 becomes 02:00)."""

ZONE = ZoneInfo(ZONE_NAME)
MONDAY = date(2026, 9, 21)
WINDOW_ID = "w1"
COVER = "cover.example_window"


def local(hour: int, minute: int = 0, day: date = MONDAY, second: int = 0) -> datetime:
    """Return a local time of the zone of the tests."""
    return datetime.combine(day, time(hour, minute, second), tzinfo=ZONE)


async def monday_morning(hass: HomeAssistant, freezer: Any) -> None:
    """Start a test on a Monday at 10:00 in a named zone with clock changes.

    Test modules turn this into an autouse fixture.
    """
    await hass.config.async_set_time_zone(ZONE_NAME)
    freezer.move_to(local(10, 0))


# The schedule of the tests: fixed times, so nothing depends on the sun.
FIXED_ROUTINE: dict[str, Any] = {
    "schedule_enabled": True,
    **{
        f"schedule_{day_type}_{edge}_kind": "fixed_time"
        for day_type in ("workday", "weekend", "holiday")
        for edge in ("morning", "evening")
    },
    "schedule_workday_morning_time": "07:00",
    "schedule_workday_evening_time": "20:00",
    "schedule_weekend_morning_time": "08:30",
    "schedule_weekend_evening_time": "21:00",
    "schedule_holiday_morning_time": "09:00",
    "schedule_holiday_evening_time": "21:30",
    # No staggering, so every member of a send is called at once; the tests
    # of the actuator adapter set a gap of their own.
    "stagger_gap": 0,
}


@dataclass(frozen=True)
class FakeSun:
    """A sun the test invents, in the named zone the runtime handed in."""

    latitude: float
    longitude: float
    elevation: float
    zone_name: str
    sunrise_at: time = time(6, 0)
    sunset_at: time = time(18, 0)
    highest: float = 40.0

    @property
    def zone(self) -> ZoneInfo:
        """Return the zone by its name."""
        return ZoneInfo(self.zone_name)

    def _at(self, on: date, at: time) -> datetime:
        return datetime.combine(on, at, tzinfo=self.zone)

    def position(self, at: datetime) -> SunPosition:
        """Return a fixed position."""
        del at
        return SunPosition(azimuth=180.0, elevation=self.highest)

    def sunrise(self, on: date) -> datetime | None:
        """Return the invented sunrise."""
        return self._at(on, self.sunrise_at)

    def sunset(self, on: date) -> datetime | None:
        """Return the invented sunset."""
        return self._at(on, self.sunset_at)

    def elevation_reached(
        self, on: date, elevation: float, *, rising: bool
    ) -> datetime | None:
        """Return the passage of an elevation, four minutes per degree."""
        if not -self.highest <= elevation <= self.highest:
            return None
        minutes = timedelta(minutes=4 * elevation)
        if rising:
            return self._at(on, time(6, 0)) + minutes
        return self._at(on, time(18, 0)) - minutes


@dataclass
class SunFactory:
    """Builds fake suns and remembers them."""

    ports: list[FakeSun] = field(default_factory=list)

    def __call__(
        self, latitude: float, longitude: float, elevation: float, zone_name: str
    ) -> FakeSun:
        """Build a fake sun for the given location and zone."""
        port = FakeSun(latitude, longitude, elevation, zone_name)
        self.ports.append(port)
        return port


def window_data(
    covers: list[str] | None = None,
    settings: dict[str, Any] | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Return the stored data of a window subentry."""
    return {
        CONF_COVERS: [COVER] if covers is None else covers,
        CONF_DRY_RUN: dry_run,
        CONF_SETTINGS: {} if settings is None else settings,
    }


def window_subentry(
    title: str = "Example window",
    window_id: str = WINDOW_ID,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a window subentry as ``MockConfigEntry`` takes it."""
    return subentry_data(
        SUBENTRY_WINDOW, title, window_data() if data is None else data, window_id
    )


async def setup_window(
    hass: HomeAssistant,
    data: dict[str, Any] | None = None,
    *,
    house: dict[str, Any] | None = None,
    covers_present: bool = True,
    freezer: Any = None,
) -> MockConfigEntry:
    """Set the entry up with one window; by default its cover is open and armed.

    ``data`` is the stored data of the window (``window_data``); with
    ``covers_present`` its covers are put on the state machine first. With
    ``freezer`` the first recompute has run when this returns.
    """
    data = window_data() if data is None else data
    register_cover_services(hass)
    if covers_present:
        for cover in data[CONF_COVERS]:
            set_cover(hass, cover)
    entry = await setup_entry(
        hass,
        {CONF_SETTINGS: FIXED_ROUTINE if house is None else house},
        subentries=[window_subentry(data=data)],
    )
    if freezer is not None:
        await settle(hass, freezer)
    return entry


def runtime_of(entry: MockConfigEntry) -> SuiteRuntime:
    """Return the runtime of the entry."""
    runtime: SuiteRuntime = entry.runtime_data.runtime
    return runtime


def controller_of(
    entry: MockConfigEntry, window_id: str = WINDOW_ID
) -> WindowController:
    """Return the controller of a window."""
    return runtime_of(entry).windows[window_id]


def phase_of(controller: WindowController) -> Phase:
    """Return the phase of a controller as it is now (a call, so nothing is narrowed)."""
    return controller.status.phase


def schedule_of(controller: WindowController) -> ScheduleResult:
    """Return the schedule's facts of the last recompute; fail if there are none."""
    schedule = controller.status.schedule
    assert schedule is not None
    return schedule


def is_active(controller: WindowController) -> bool:
    """Return whether a controller listens and keeps timers, as it is now."""
    return controller.active


@dataclass(frozen=True)
class CoverCall:
    """One call of a cover action, as the stand-in services received it.

    ``target`` is the position of ``set_cover_position``, 100 for
    ``open_cover`` and 0 for ``close_cover``; ``at`` is the time of the call.
    """

    member_id: str
    service: str
    target: Position
    context_id: str
    at: datetime


COVER_CALLS: HassKey[list[CoverCall]] = HassKey("test_cover_calls")

_TARGET_OF: dict[str, int | None] = {
    SERVICE_SET_COVER_POSITION: None,
    SERVICE_OPEN_COVER: 100,
    SERVICE_CLOSE_COVER: 0,
}


def register_cover_services(hass: HomeAssistant) -> list[CoverCall]:
    """Register stand-ins for the three cover actions that record every call.

    No cover platform is loaded and no real cover moves: the stand-ins only
    write down what the actuator adapter called. A test that wants a call
    to fail registers its own handler under the same name afterwards.
    """
    calls = hass.data.setdefault(COVER_CALLS, [])

    async def record(call: ServiceCall) -> None:
        fixed = _TARGET_OF[call.service]
        target = call.data[ATTR_POSITION] if fixed is None else fixed
        entity_ids = call.data[ATTR_ENTITY_ID]
        for member_id in [entity_ids] if isinstance(entity_ids, str) else entity_ids:
            calls.append(
                CoverCall(
                    member_id,
                    call.service,
                    Position(target),
                    call.context.id,
                    dt_util.utcnow(),
                )
            )

    for service in _TARGET_OF:
        hass.services.async_register(COVER_DOMAIN, service, record)
    return calls


def cover_calls(hass: HomeAssistant) -> list[CoverCall]:
    """Return the calls the stand-in services recorded so far."""
    return hass.data.setdefault(COVER_CALLS, [])


def commands_sent(entry: MockConfigEntry) -> list[CoverCall]:
    """Return the cover actions called for the windows of the installation."""
    return cover_calls(runtime_of(entry).hass)


async def settle(hass: HomeAssistant, freezer: Any, seconds: float = 1.5) -> None:
    """Let the coalescing of the runtime run out: advance time and fire the timers."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def advance(hass: HomeAssistant, freezer: Any, to: datetime) -> None:
    """Move the time to ``to`` and fire everything that is due, then settle."""
    freezer.move_to(to)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await settle(hass, freezer)
