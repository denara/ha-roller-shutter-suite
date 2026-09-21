"""What the tests of the schedule share: a zone, an invented sun, a window, snapshots.

Everything runs against a time that the test states and a sun that the test
invents. The zone is a named one with daylight saving time. In 2026 its clocks
go forward on 29 March (02:00 becomes 03:00) and back on 25 October (03:00
becomes 02:00). 21 September 2026 is a Monday.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from custom_components.roller_shutter_suite.core.model import (
    SCHEDULE_EDGES,
    TRIGGER_FIELDS,
    AnySourceValue,
    CapabilityProfile,
    Controls,
    DayTriggers,
    MemberConfig,
    MemberObservation,
    MovementState,
    Observation,
    Position,
    ScheduleTargets,
    SunPosition,
    Trigger,
    TriggerKind,
    WindowConfig,
    WindowObservation,
    WindowState,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.ports import Sun
from custom_components.roller_shutter_suite.core.schedule import (
    ScheduleResult,
    build_sun_almanac,
    evaluate_schedule,
)

ZONE = ZoneInfo("Europe/Berlin")
SEED = 20260921
MEMBER = "cover.example_window"
MONDAY = date(2026, 9, 21)
FRIDAY = date(2026, 9, 25)
SATURDAY = date(2026, 9, 26)
SUNDAY = date(2026, 9, 27)
CLOCKS_FORWARD = date(2026, 3, 29)
CLOCKS_BACK = date(2026, 10, 25)

OPEN = Position(100)
CLOSED = Position(0)
SUMMER_EVENING = Position(30)

EARLY = (time(5, 0), time(9, 0))
LATE = (time(16, 0), time(22, 0))


def fixed(hour: int, minute: int = 0, second: int = 0) -> Trigger:
    """Return a trigger at a fixed time; its clamps are not in its way."""
    return Trigger(
        TriggerKind.FIXED_TIME,
        time=time(hour, minute, second),
        not_before=time(0, 0),
        not_after=time(23, 59),
    )


def sun_event(clamps: tuple[time, time], offset_minutes: int = 0) -> Trigger:
    """Return a trigger at sunrise or sunset with an offset, between the clamps."""
    return Trigger(
        TriggerKind.SUN_EVENT,
        time=clamps[0],
        offset_minutes=offset_minutes,
        not_before=clamps[0],
        not_after=clamps[1],
    )


def elevation_trigger(elevation: float, clamps: tuple[time, time]) -> Trigger:
    """Return a trigger at a sun elevation, between the clamps."""
    return Trigger(
        TriggerKind.ELEVATION,
        time=clamps[0],
        elevation=elevation,
        not_before=clamps[0],
        not_after=clamps[1],
    )


def flat(day_type: str, triggers: DayTriggers) -> dict[str, Any]:
    """Return the triggers of one day type as the flat fields of a window."""
    return {
        f"schedule_{day_type}_{edge}_{name}": getattr(getattr(triggers, edge), name)
        for edge in SCHEDULE_EDGES
        for name in TRIGGER_FIELDS
    }


def config(window_id: str = "window_example", **changes: Any) -> WindowConfig:
    """Return a window whose schedule the tests know by heart.

    Workdays 06:30 and 20:00, weekends 08:30 and 21:00, public holidays 09:00
    and 21:30, all fixed; fully open by day and fully closed by night.
    ``workday=``, ``weekend=`` and ``holiday=`` take ``DayTriggers``,
    ``targets=`` takes ``ScheduleTargets``; every other change is a field of
    the window, with or without the prefix ``schedule_``.
    """
    fields: dict[str, Any] = {
        **flat("workday", DayTriggers(fixed(6, 30), fixed(20, 0))),
        **flat("weekend", DayTriggers(fixed(8, 30), fixed(21, 0))),
        **flat("holiday", DayTriggers(fixed(9, 0), fixed(21, 30))),
    }
    names = set(WindowConfig.__dataclass_fields__)
    for key, value in changes.items():
        if isinstance(value, DayTriggers):
            fields |= flat(key, value)
        elif isinstance(value, ScheduleTargets):
            fields |= {
                "schedule_morning_position": value.morning_position,
                "schedule_evening_position": value.evening_position,
                "schedule_evening_position_summer": value.evening_position_summer,
            }
        else:
            fields[key if key in names else f"schedule_{key}"] = value
    profile = CapabilityProfile(
        supports_open_close=True,
        supports_set_position=True,
        supports_stop=True,
        reports_position=True,
        travel_time_up=timedelta(seconds=20),
        travel_time_down=timedelta(seconds=18),
    )
    return WindowConfig(window_id, (MemberConfig(MEMBER, profile),), **fields)


CONFIG = config()


@dataclass(frozen=True)
class FakeSun:
    """A sun the test invents: fixed local times, four minutes per degree.

    It rises and sets at the given local times, or not at all. It passes an
    elevation four minutes per degree after sunrise and before sunset, as long
    as the elevation lies between the lowest and the highest of the day. With
    ``naive`` it answers without a zone, which the core has to refuse.
    """

    sunrise_at: time | None = time(6, 0)
    sunset_at: time | None = time(18, 0)
    highest: float = 40.0
    lowest: float = -40.0
    naive: bool = False

    def _at(self, on: date, at: time) -> datetime:
        return datetime.combine(on, at, tzinfo=None if self.naive else ZONE)

    def position(self, at: datetime) -> SunPosition:
        """Return the highest elevation of the day, whatever the time."""
        del at
        return SunPosition(azimuth=180.0, elevation=self.highest)

    def sunrise(self, on: date) -> datetime | None:
        """Return the invented sunrise."""
        return None if self.sunrise_at is None else self._at(on, self.sunrise_at)

    def sunset(self, on: date) -> datetime | None:
        """Return the invented sunset."""
        return None if self.sunset_at is None else self._at(on, self.sunset_at)

    def elevation_reached(
        self, on: date, elevation: float, *, rising: bool
    ) -> datetime | None:
        """Return the passage of an elevation, four minutes per degree."""
        if not self.lowest <= elevation <= self.highest:
            return None
        minutes = timedelta(minutes=4 * elevation)
        if rising:
            return self._at(on, time(6, 0)) + minutes
        return self._at(on, time(18, 0)) - minutes


SUN: Sun = FakeSun()


def local(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    """Return a local time of the zone of the tests."""
    return datetime.combine(day, time(hour, minute, second), tzinfo=ZONE)


def snapshot(
    at: datetime,
    sources: dict[str, AnySourceValue] | None = None,
    state: WindowState | None = None,
    **more: Any,
) -> WorldSnapshot:
    """Return a world snapshot; the one place of these tests that builds one."""
    return WorldSnapshot(
        time=at,
        sun=SunPosition(azimuth=180.0, elevation=10.0),
        sources=sources or {},
        observation=more.pop(
            "observation",
            WindowObservation(
                (MemberObservation(MEMBER, Observation(MovementState.RESTING, OPEN)),)
            ),
        ),
        state=WindowState() if state is None else state,
        controls=more.pop("controls", Controls(dry_run=False)),
        **more,
    )


def snapshot_with_almanac(  # noqa: PLR0913 - every part of a situation can be varied
    at: datetime,
    window: WindowConfig = CONFIG,
    *,
    sources: dict[str, AnySourceValue] | None = None,
    state: WindowState | None = None,
    sun: Sun = SUN,
    seed: int | None = SEED,
    **more: Any,
) -> WorldSnapshot:
    """Return a snapshot as the runtime builds it: almanac and seed are data."""
    return snapshot(
        at,
        sources,
        state,
        almanac=build_sun_almanac(window, at, sun),
        installation_seed=seed,
        **more,
    )


def evaluate(  # noqa: PLR0913 - every part of a situation can be varied
    at: datetime,
    window: WindowConfig = CONFIG,
    *,
    sources: dict[str, AnySourceValue] | None = None,
    state: WindowState | None = None,
    sun: Sun = SUN,
    seed: int = SEED,
) -> ScheduleResult:
    """Evaluate the schedule with the sun port itself, as the simulation does."""
    return evaluate_schedule(window, snapshot(at, sources, state), sun, seed=seed)
