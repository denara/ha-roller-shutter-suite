"""The schedule: triggers, clamps, day types, parts of the day, next planned action.

Everything runs against a time that the test states and a sun that the test
invents. The zone is a named one with daylight saving time. In 2026 its clocks
go forward on 29 March (02:00 becomes 03:00) and back on 25 October (03:00
becomes 02:00). 21 September 2026 is a Monday.
"""

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from custom_components.roller_shutter_suite.core.model import (
    AnySourceValue,
    CapabilityProfile,
    DayType,
    Direction,
    HeldInput,
    LatchedDayType,
    Layer,
    MemberConfig,
    MemberObservation,
    MovementState,
    Observation,
    Position,
    ScheduleProfile,
    SourceValue,
    SunPosition,
    WindowConfig,
    WindowObservation,
    WindowState,
    WishKind,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.ports import Sun
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from custom_components.roller_shutter_suite.core.schedule import (
    SCHEDULE_NOT_CONFIGURED,
    DayOfYear,
    DayTriggers,
    Edge,
    PartOfDay,
    PlannedAction,
    ScheduleResult,
    ScheduleSettings,
    ScheduleTargets,
    Trigger,
    TriggerKind,
    day_type_by_weekday,
    evaluate_schedule,
    local_instant,
    morning_condition_fulfilled,
    random_offset,
    trigger_instant,
)
from custom_components.roller_shutter_suite.core.schedule.local_time import zone_of

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


def _window(window_id: str = "window_example", **more: Any) -> WindowConfig:
    profile = CapabilityProfile(
        supports_open_close=True,
        supports_set_position=True,
        supports_stop=True,
        reports_position=True,
        travel_time_up=timedelta(seconds=20),
        travel_time_down=timedelta(seconds=18),
    )
    return WindowConfig(window_id, (MemberConfig(MEMBER, profile),), **more)


WINDOW = _window()


def _fixed(hour: int, minute: int = 0) -> Trigger:
    return Trigger(TriggerKind.FIXED_TIME, at=time(hour, minute))


def _sun_event(clamps: tuple[time, time], offset: timedelta = timedelta(0)) -> Trigger:
    return Trigger(
        TriggerKind.SUN_EVENT,
        offset=offset,
        not_before=clamps[0],
        not_after=clamps[1],
    )


def _elevation(elevation: float, clamps: tuple[time, time]) -> Trigger:
    return Trigger(
        TriggerKind.ELEVATION,
        elevation=elevation,
        not_before=clamps[0],
        not_after=clamps[1],
    )


def _settings(**changes: Any) -> ScheduleSettings:
    arguments: dict[str, Any] = {
        "workday": DayTriggers(_fixed(6, 30), _fixed(20, 0)),
        "weekend": DayTriggers(_fixed(8, 30), _fixed(21, 0)),
        "holiday": DayTriggers(_fixed(9, 0), _fixed(21, 30)),
        "targets": {ScheduleProfile.DEFAULT: ScheduleTargets(OPEN, CLOSED)},
    }
    return ScheduleSettings(**(arguments | changes))


SETTINGS = _settings()


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


def _local(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute, second), tzinfo=ZONE)


def _snapshot(
    at: datetime,
    sources: dict[str, AnySourceValue] | None = None,
    state: WindowState | None = None,
) -> WorldSnapshot:
    return WorldSnapshot(
        time=at,
        sun=SunPosition(azimuth=180.0, elevation=10.0),
        sources=sources or {},
        observation=WindowObservation(
            (MemberObservation(MEMBER, Observation(MovementState.RESTING, OPEN)),)
        ),
        state=WindowState() if state is None else state,
    )


def _evaluate(  # noqa: PLR0913 - every part of a situation can be varied
    at: datetime,
    settings: ScheduleSettings = SETTINGS,
    *,
    sources: dict[str, AnySourceValue] | None = None,
    state: WindowState | None = None,
    sun: Sun = SUN,
    window: WindowConfig = WINDOW,
    seed: int = SEED,
) -> ScheduleResult:
    return evaluate_schedule(
        settings, window, _snapshot(at, sources, state), sun, seed=seed
    )


# --- Local times and the two days of a clock change ---------------------------------------


@pytest.mark.parametrize(
    ("day", "local", "expected_utc"),
    [
        (MONDAY, time(6, 30), datetime(2026, 9, 21, 4, 30, tzinfo=UTC)),
        (date(2026, 1, 15), time(6, 30), datetime(2026, 1, 15, 5, 30, tzinfo=UTC)),
        # 02:30 does not exist: it moves forward by the gap and happens at 03:30.
        (CLOCKS_FORWARD, time(2, 30), datetime(2026, 3, 29, 1, 30, tzinfo=UTC)),
        (CLOCKS_FORWARD, time(3, 30), datetime(2026, 3, 29, 1, 30, tzinfo=UTC)),
        (CLOCKS_FORWARD, time(1, 59), datetime(2026, 3, 29, 0, 59, tzinfo=UTC)),
        # 02:30 exists twice: the first occurrence counts.
        (CLOCKS_BACK, time(2, 30), datetime(2026, 10, 25, 0, 30, tzinfo=UTC)),
        (CLOCKS_BACK, time(2, 30, fold=1), datetime(2026, 10, 25, 0, 30, tzinfo=UTC)),
        (CLOCKS_BACK, time(3, 0), datetime(2026, 10, 25, 2, 0, tzinfo=UTC)),
    ],
    ids=[
        "summer time",
        "standard time",
        "skipped time",
        "the same instant as the skipped time",
        "just before the skipped hour",
        "repeated time",
        "repeated time, second pass asked for",
        "after the repeated hour",
    ],
)
def test_a_local_time_is_one_defined_instant(
    day: date, local: time, expected_utc: datetime
) -> None:
    """A skipped time moves by the gap, a repeated one means its first pass."""
    instant = local_instant(day, local, ZONE)

    assert instant == expected_utc
    assert instant.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    ("day", "seven_in_utc"),
    [
        (CLOCKS_FORWARD, datetime(2026, 3, 29, 5, 0, tzinfo=UTC)),
        (CLOCKS_BACK, datetime(2026, 10, 25, 6, 0, tzinfo=UTC)),
    ],
    ids=["clocks forward", "clocks back"],
)
def test_a_trigger_at_seven_runs_at_seven_on_the_day_of_a_clock_change(
    day: date, seven_in_utc: datetime
) -> None:
    """The rule touches only times inside the gap or the repeated hour.

    07:00 is 07:00 on the clock of that day, although that is six or eight
    elapsed hours after local midnight.
    """
    at_seven = DayTriggers(_fixed(7, 0), _fixed(20, 0))
    settings = _settings(workday=at_seven, weekend=at_seven)

    before = _evaluate(_local(day, 6, 59, 59), settings)
    at = _evaluate(_local(day, 7, 0), settings)

    assert local_instant(day, time(7, 0), ZONE) == seven_in_utc
    assert before.part_of_day is PartOfDay.NIGHT
    assert at.part_of_day is PartOfDay.DAY
    assert at.morning_trigger == seven_in_utc
    assert at.morning_trigger.astimezone(ZONE).time() == time(7, 0)
    assert seven_in_utc - local_instant(day, time(0, 0), ZONE) != timedelta(hours=7)


def test_the_schedule_refuses_a_time_without_a_zone() -> None:
    """A naive time would be read in the zone of the machine."""
    assert zone_of(_local(MONDAY, 12)) is ZONE
    with pytest.raises(ValueError, match="timezone-aware"):
        zone_of(datetime(2026, 9, 21, 12, 0))  # noqa: DTZ001 - the rejected case


# --- Triggers and clamps ----------------------------------------------------------------

_EARLY = (time(5, 0), time(9, 0))
_LATE = (time(16, 0), time(22, 0))
POLAR_NIGHT = FakeSun(sunrise_at=None, sunset_at=None, highest=-5.0)
POLAR_DAY = FakeSun(sunrise_at=None, sunset_at=None, highest=50.0, lowest=5.0)


@pytest.mark.parametrize(
    ("trigger", "edge", "sun", "expected"),
    [
        (_fixed(6, 30), Edge.MORNING, SUN, time(6, 30)),
        (_fixed(20, 0), Edge.EVENING, SUN, time(20, 0)),
        (_sun_event(_EARLY), Edge.MORNING, SUN, time(6, 0)),
        (
            _sun_event(_EARLY, timedelta(minutes=45)),
            Edge.MORNING,
            SUN,
            time(6, 45),
        ),
        (
            _sun_event(_LATE, timedelta(minutes=-30)),
            Edge.EVENING,
            SUN,
            time(17, 30),
        ),
        (
            _elevation(10, _EARLY),
            Edge.MORNING,
            SUN,
            time(6, 40),
        ),
        (
            _elevation(-6.0, _LATE),
            Edge.EVENING,
            SUN,
            time(18, 24),
        ),
    ],
    ids=[
        "fixed time, morning",
        "fixed time, evening",
        "sunrise",
        "sunrise with offset",
        "sunset with offset",
        "elevation, rising",
        "elevation, falling",
    ],
)
def test_each_kind_of_trigger(
    trigger: Trigger, edge: Edge, sun: Sun, expected: time
) -> None:
    """Fixed time, sunrise or sunset with an offset, and sun elevation."""
    instant = trigger_instant(trigger, edge, MONDAY, zone=ZONE, sun=sun)

    assert instant == datetime.combine(MONDAY, expected, tzinfo=ZONE)


@pytest.mark.parametrize(
    ("trigger", "edge", "sun", "expected"),
    [
        (
            Trigger(
                TriggerKind.SUN_EVENT, not_before=time(6, 30), not_after=time(9, 0)
            ),
            Edge.MORNING,
            SUN,
            time(6, 30),
        ),
        (
            Trigger(
                TriggerKind.SUN_EVENT, not_before=time(4, 0), not_after=time(5, 30)
            ),
            Edge.MORNING,
            SUN,
            time(5, 30),
        ),
        (
            Trigger(
                TriggerKind.SUN_EVENT, not_before=time(19, 0), not_after=time(22, 0)
            ),
            Edge.EVENING,
            SUN,
            time(19, 0),
        ),
        (
            Trigger(
                TriggerKind.SUN_EVENT, not_before=time(16, 0), not_after=time(17, 0)
            ),
            Edge.EVENING,
            SUN,
            time(17, 0),
        ),
        (
            Trigger(
                TriggerKind.ELEVATION,
                elevation=30,
                not_before=time(5, 0),
                not_after=time(7, 30),
            ),
            Edge.MORNING,
            SUN,
            time(7, 30),
        ),
        (
            Trigger(
                TriggerKind.ELEVATION,
                elevation=30,
                not_before=time(16, 30),
                not_after=time(22, 0),
            ),
            Edge.EVENING,
            SUN,
            time(16, 30),
        ),
    ],
    ids=[
        "sunrise before 'not before'",
        "sunrise after 'not after'",
        "sunset before 'not before'",
        "sunset after 'not after'",
        "rising elevation after 'not after'",
        "falling elevation before 'not before'",
    ],
)
def test_clamps_hold_on_both_sides(
    trigger: Trigger, edge: Edge, sun: Sun, expected: time
) -> None:
    """'Not before' and 'not after' clamp the triggers of the sun."""
    instant = trigger_instant(trigger, edge, MONDAY, zone=ZONE, sun=sun)

    assert instant == datetime.combine(MONDAY, expected, tzinfo=ZONE)


@pytest.mark.parametrize(
    ("trigger", "edge", "sun", "expected"),
    [
        # The sun stays below the elevation: no morning by itself, evening at once.
        (
            _elevation(45, _EARLY),
            Edge.MORNING,
            SUN,
            time(9, 0),
        ),
        (
            _elevation(45, _LATE),
            Edge.EVENING,
            SUN,
            time(16, 0),
        ),
        # The sun stays above the elevation: morning at once, no evening by itself.
        (
            _elevation(-3, _EARLY),
            Edge.MORNING,
            POLAR_DAY,
            time(5, 0),
        ),
        (
            _elevation(-3, _LATE),
            Edge.EVENING,
            POLAR_DAY,
            time(22, 0),
        ),
        (_sun_event(_EARLY), Edge.MORNING, POLAR_NIGHT, time(9, 0)),
        (_sun_event(_LATE), Edge.EVENING, POLAR_NIGHT, time(16, 0)),
        (_sun_event(_EARLY), Edge.MORNING, POLAR_DAY, time(5, 0)),
        (_sun_event(_LATE), Edge.EVENING, POLAR_DAY, time(22, 0)),
    ],
    ids=[
        "elevation too high, morning",
        "elevation too high, evening",
        "elevation too low, morning",
        "elevation too low, evening",
        "no sunrise in the polar night",
        "no sunset in the polar night",
        "no sunrise in the polar day",
        "no sunset in the polar day",
    ],
)
def test_a_moment_that_never_comes_falls_on_the_clamp_in_its_direction(
    trigger: Trigger, edge: Edge, sun: Sun, expected: time
) -> None:
    """The random offset does not move it off the clamp either."""
    instant = trigger_instant(
        trigger, edge, MONDAY, zone=ZONE, sun=sun, offset=timedelta(minutes=17)
    )

    assert instant == datetime.combine(MONDAY, expected, tzinfo=ZONE)


def test_a_trigger_stays_on_its_own_date() -> None:
    """An offset cannot push a trigger across local midnight."""
    late = trigger_instant(
        _fixed(23, 50),
        Edge.EVENING,
        MONDAY,
        zone=ZONE,
        sun=SUN,
        offset=timedelta(minutes=25),
    )
    early = trigger_instant(
        _fixed(0, 10),
        Edge.MORNING,
        MONDAY,
        zone=ZONE,
        sun=SUN,
        offset=timedelta(minutes=-25),
    )

    assert late == _local(date(2026, 9, 22), 0)
    assert early == _local(MONDAY, 0)


def test_a_sun_port_that_answers_without_a_zone_is_refused() -> None:
    """The core never guesses a zone, because that would mean reading the machine."""
    sun_based = DayTriggers(
        _sun_event(_EARLY),
        _elevation(-6, _LATE),
    )
    settings = _settings(workday=sun_based)

    with pytest.raises(ValueError, match="sun port must be timezone-aware"):
        _evaluate(_local(MONDAY, 12), settings, sun=FakeSun(naive=True))
    with pytest.raises(ValueError, match="sun port must be timezone-aware"):
        trigger_instant(
            sun_based.evening, Edge.EVENING, MONDAY, zone=ZONE, sun=FakeSun(naive=True)
        )


# --- Random offset -------------------------------------------------------------------------

RANGE = timedelta(minutes=15)


def test_random_offset_is_off_by_default() -> None:
    """A range of zero gives no offset."""
    assert random_offset(SEED, "window_a", MONDAY, Edge.MORNING, timedelta(0)) == (
        timedelta(0)
    )
    assert _evaluate(_local(MONDAY, 12)).morning_trigger == _local(MONDAY, 6, 30)


def test_random_offset_is_reproducible_and_stable_within_a_day() -> None:
    """The same seed, window, date and trigger give the same offset, always."""
    first = random_offset(SEED, "window_a", MONDAY, Edge.MORNING, RANGE)
    settings = _settings(random_offset=RANGE)
    triggers = {
        _evaluate(_local(MONDAY, hour), settings).morning_trigger for hour in range(24)
    }

    assert first == random_offset(SEED, "window_a", MONDAY, Edge.MORNING, RANGE)
    assert len(triggers) == 1


def test_random_offset_differs_between_windows_dates_triggers_and_seeds() -> None:
    """Every part of the key changes the offset."""
    base = random_offset(SEED, "window_a", MONDAY, Edge.MORNING, RANGE)
    others = [
        random_offset(SEED, "window_b", MONDAY, Edge.MORNING, RANGE),
        random_offset(SEED, "window_a", FRIDAY, Edge.MORNING, RANGE),
        random_offset(SEED, "window_a", MONDAY, Edge.EVENING, RANGE),
        random_offset(SEED + 1, "window_a", MONDAY, Edge.MORNING, RANGE),
    ]
    settings = _settings(random_offset=RANGE)
    at = _local(MONDAY, 12)

    assert all(other != base for other in others)
    assert (
        _evaluate(at, settings, window=_window("window_a")).morning_trigger
        != _evaluate(at, settings, window=_window("window_b")).morning_trigger
    )


def test_random_offset_covers_its_range_and_never_leaves_it() -> None:
    """Whole seconds within plus and minus the range, on both sides of zero."""
    offsets = [
        random_offset(SEED, "window_a", MONDAY + timedelta(days=day), edge, RANGE)
        for day in range(200)
        for edge in Edge
    ]

    assert all(-RANGE <= offset <= RANGE for offset in offsets)
    assert min(offsets) < timedelta(minutes=-12)
    assert max(offsets) > timedelta(minutes=12)
    assert all(offset.microseconds == 0 for offset in offsets)


def test_random_offset_is_applied_before_the_clamps() -> None:
    """A sunrise next to its clamp moves with the offset, but never past the clamp."""
    trigger = Trigger(
        TriggerKind.SUN_EVENT, not_before=time(5, 55), not_after=time(6, 5)
    )
    settings = _settings(
        workday=DayTriggers(trigger, _fixed(20, 0)),
        weekend=DayTriggers(trigger, _fixed(21, 0)),
        random_offset=timedelta(minutes=30),
    )
    mornings = []
    for ahead in range(60):
        day = MONDAY + timedelta(days=ahead)
        result = _evaluate(_local(day, 12), settings)
        assert _local(day, 5, 55) <= result.morning_trigger <= _local(day, 6, 5)
        mornings.append(result.morning_trigger - _local(day, 6, 0))

    assert timedelta(minutes=-5) in mornings
    assert timedelta(minutes=5) in mornings
    assert set(mornings) - {timedelta(minutes=-5), timedelta(minutes=5)}


# --- Parts of the day and the wish -----------------------------------------------------------


@pytest.mark.parametrize(
    ("at", "part", "position", "direction", "reason"),
    [
        (
            _local(MONDAY, 0),
            PartOfDay.NIGHT,
            CLOSED,
            Direction.LOWER_ONLY,
            ReasonCode.SCHEDULE_NIGHT,
        ),
        (
            _local(MONDAY, 6, 29, 59),
            PartOfDay.NIGHT,
            CLOSED,
            Direction.LOWER_ONLY,
            ReasonCode.SCHEDULE_NIGHT,
        ),
        (
            _local(MONDAY, 6, 30),
            PartOfDay.DAY,
            OPEN,
            Direction.RAISE_ONLY,
            ReasonCode.SCHEDULE_DAY,
        ),
        (
            _local(MONDAY, 19, 59, 59),
            PartOfDay.DAY,
            OPEN,
            Direction.RAISE_ONLY,
            ReasonCode.SCHEDULE_DAY,
        ),
        (
            _local(MONDAY, 20, 0),
            PartOfDay.NIGHT,
            CLOSED,
            Direction.LOWER_ONLY,
            ReasonCode.SCHEDULE_NIGHT,
        ),
        (
            _local(MONDAY, 23, 59, 59),
            PartOfDay.NIGHT,
            CLOSED,
            Direction.LOWER_ONLY,
            ReasonCode.SCHEDULE_NIGHT,
        ),
    ],
    ids=[
        "midnight",
        "before the morning",
        "morning",
        "before the evening",
        "evening",
        "late",
    ],
)
def test_the_wish_is_the_target_of_the_current_part_of_the_day(
    at: datetime,
    part: PartOfDay,
    position: Position,
    direction: Direction,
    reason: ReasonCode,
) -> None:
    """The day target only raises, the night target only lowers."""
    result = _evaluate(at)

    assert result.part_of_day is part
    assert result.wish.layer is Layer.SCHEDULE
    assert result.wish.kind is WishKind.TARGET
    assert result.wish.position == position
    assert result.wish.direction is direction
    assert result.wish.reason is reason


def test_nothing_is_replayed_a_fresh_start_gives_the_same_answer() -> None:
    """A core that ran for a week and one that just started agree at every hour."""
    settings = _settings(
        workday=DayTriggers(
            _sun_event(_EARLY),
            _elevation(-6, _LATE),
        ),
        workday_source="workday",
        holiday_source="holiday",
        random_offset=RANGE,
    )
    sources: dict[str, AnySourceValue] = {
        "workday": SourceValue.of(True),
        "holiday": SourceValue.of(False),
    }
    carried = WindowState()
    start = _local(MONDAY, 0)
    for hour in range(7 * 24):
        at = (start.astimezone(UTC) + timedelta(hours=hour)).astimezone(ZONE)
        running = _evaluate(at, settings, sources=sources, state=carried)
        started = _evaluate(at, settings, sources=sources)
        carried = running.state

        assert running.wish == started.wish
        assert running.part_of_day is started.part_of_day
        assert running.next_action == started.next_action
        assert running == _evaluate(at, settings, sources=sources, state=running.state)


def test_the_same_snapshot_gives_the_same_result() -> None:
    """The function keeps nothing between two calls."""
    at = _local(MONDAY, 7)

    assert _evaluate(at) == _evaluate(at)
    assert _evaluate(at).state == WindowState(
        latched_day_types=(LatchedDayType(MONDAY, DayType.WORKDAY),)
    )


def test_the_schedule_changes_nothing_else_in_the_persisted_state() -> None:
    """Only what the schedule has to remember is replaced."""
    before = WindowState(
        fire_unacknowledged=True,
        last_comfort_movement=_local(MONDAY, 6),
        held_frost=HeldInput(value=True, seen_at=_local(MONDAY, 5)),
    )

    after = _evaluate(_local(MONDAY, 7), state=before).state

    assert after == replace(
        before, latched_day_types=(LatchedDayType(MONDAY, DayType.WORKDAY),)
    )


def test_a_window_without_schedule_settings_has_no_opinion() -> None:
    """Not configured: the layer steps aside and says so."""
    assert SCHEDULE_NOT_CONFIGURED.layer is Layer.SCHEDULE
    assert SCHEDULE_NOT_CONFIGURED.kind is WishKind.NO_OPINION
    assert SCHEDULE_NOT_CONFIGURED.reason is ReasonCode.NOT_CONFIGURED


def test_the_condition_of_the_morning_opening_is_always_fulfilled() -> None:
    """The input exists; a source that reports 'off' changes nothing yet."""
    window = _window(morning_condition_source="somebody_awake")
    sources: dict[str, AnySourceValue] = {"somebody_awake": SourceValue.of(False)}
    snapshot = _snapshot(_local(MONDAY, 7), sources)

    assert morning_condition_fulfilled(window, snapshot) is True
    assert morning_condition_fulfilled(WINDOW, _snapshot(_local(MONDAY, 7))) is True
    assert (
        _evaluate(_local(MONDAY, 7), window=window, sources=sources).part_of_day
        is PartOfDay.DAY
    )


def test_targets_are_looked_up_through_the_profile_key_of_the_window() -> None:
    """The key has one value; the lookup goes through it all the same."""
    settings = _settings(
        targets={ScheduleProfile.DEFAULT: ScheduleTargets(Position(80), Position(10))}
    )
    window = _window(schedule_profile=ScheduleProfile.DEFAULT)

    assert _evaluate(_local(MONDAY, 12), settings, window=window).wish.position == (
        Position(80)
    )
    assert _evaluate(_local(MONDAY, 22), settings, window=window).wish.position == (
        Position(10)
    )


# --- Day types -------------------------------------------------------------------------------

ON = SourceValue.of(True)
OFF = SourceValue.of(False)
WITH_SOURCES = _settings(workday_source="workday", holiday_source="holiday")
MISSING: dict[str, AnySourceValue] = {
    "workday": SourceValue.unavailable(),
    "holiday": SourceValue.unavailable(),
}


def test_the_day_of_the_week_is_rule_three() -> None:
    """Monday to Friday is a workday, Saturday and Sunday are weekend."""
    days = [MONDAY + timedelta(days=ahead) for ahead in range(7)]

    assert [day_type_by_weekday(day) for day in days] == [
        *[DayType.WORKDAY] * 5,
        *[DayType.WEEKEND] * 2,
    ]


@pytest.mark.parametrize(
    ("settings", "day", "sources", "expected"),
    [
        (SETTINGS, MONDAY, {}, DayType.WORKDAY),
        (SETTINGS, SATURDAY, {}, DayType.WEEKEND),
        (SETTINGS, SUNDAY, {}, DayType.WEEKEND),
        (WITH_SOURCES, MONDAY, {"workday": ON, "holiday": OFF}, DayType.WORKDAY),
        (WITH_SOURCES, MONDAY, {"workday": OFF, "holiday": OFF}, DayType.WEEKEND),
        (WITH_SOURCES, SATURDAY, {"workday": ON, "holiday": OFF}, DayType.WORKDAY),
        (WITH_SOURCES, MONDAY, {"workday": ON, "holiday": ON}, DayType.HOLIDAY),
        (WITH_SOURCES, MONDAY, {"workday": OFF, "holiday": ON}, DayType.HOLIDAY),
        (
            WITH_SOURCES,
            MONDAY,
            {"workday": SourceValue.unavailable(), "holiday": ON},
            DayType.HOLIDAY,
        ),
        (
            _settings(holiday_source="holiday"),
            MONDAY,
            {"holiday": OFF},
            DayType.WORKDAY,
        ),
        (
            _settings(holiday_source="holiday"),
            SUNDAY,
            {"holiday": OFF},
            DayType.WEEKEND,
        ),
        (_settings(holiday_source="holiday"), SUNDAY, {"holiday": ON}, DayType.HOLIDAY),
        (_settings(workday_source="workday"), SUNDAY, {"workday": ON}, DayType.WORKDAY),
    ],
    ids=[
        "no source, Monday",
        "no source, Saturday",
        "no source, Sunday",
        "workday source on",
        "workday source off",
        "workday source on at a Saturday",
        "holiday wins over workday",
        "holiday, workday off",
        "holiday decides alone",
        "holiday source only, off on a Monday",
        "holiday source only, off on a Sunday",
        "holiday source only, on",
        "workday source only",
    ],
)
def test_each_day_type(
    settings: ScheduleSettings,
    day: date,
    sources: dict[str, AnySourceValue],
    expected: DayType,
) -> None:
    """Holiday first, then the workday source, then the day of the week.

    At night the day type is a preview; at noon it is fixed for the date.
    """
    preview = _evaluate(_local(day, 3), settings, sources=sources)
    fixed = _evaluate(_local(day, 12), settings, sources=sources, state=preview.state)

    assert preview.day_type is expected
    assert preview.day_type_latched is False
    assert preview.day_type_reason is None
    assert preview.state.latched_day_types == ()
    assert preview.morning_trigger == local_instant(
        day, settings.triggers_for(expected).morning.fixed_time, ZONE
    )
    assert fixed.day_type is expected
    assert fixed.day_type_latched is True
    assert fixed.day_type_reason is None
    assert fixed.state.latched_day_types == (LatchedDayType(day, expected),)


@pytest.mark.parametrize(
    "sources",
    [
        {"workday": SourceValue.unavailable(), "holiday": OFF},
        {"workday": SourceValue.unknown(), "holiday": OFF},
        {"workday": ON, "holiday": SourceValue.unavailable()},
        {"workday": ON, "holiday": SourceValue.unknown()},
        {"holiday": OFF},
        {},
        {"workday": SourceValue.of("on"), "holiday": OFF},
        {"workday": SourceValue.of(1), "holiday": OFF},
    ],
    ids=[
        "workday unavailable",
        "workday unknown",
        "holiday unavailable",
        "holiday unknown",
        "workday not in the snapshot",
        "nothing in the snapshot",
        "workday is a text",
        "workday is a number",
    ],
)
def test_an_input_without_a_value_leads_to_the_fallback_with_its_reason(
    sources: dict[str, AnySourceValue],
) -> None:
    """The day of the week stands in for the time being; nothing is latched, nothing raises."""
    result = _evaluate(_local(SATURDAY, 3), WITH_SOURCES, sources=sources)

    assert result.day_type is DayType.WEEKEND
    assert result.day_type_latched is False
    assert result.day_type_reason is ReasonCode.DAY_TYPE_FALLBACK
    assert result.state.latched_day_types == ()
    assert result.part_of_day is PartOfDay.NIGHT


def test_the_source_changes_30_seconds_after_midnight() -> None:
    """An evaluation at 00:00:10 still sees yesterday's value; it fixes nothing.

    Sunday has ended. The workday sensor still says "off" at 00:00:10 and
    switches at 00:00:30. The morning trigger computed afterwards and the
    latched day type are Monday's.
    """
    settings = _settings(workday_source="workday")
    the_day_before = MONDAY - timedelta(days=1)
    sunday = _evaluate(
        _local(the_day_before, 23, 59), settings, sources={"workday": OFF}
    )
    too_early = _evaluate(
        _local(MONDAY, 0, 0, 10), settings, sources={"workday": OFF}, state=sunday.state
    )
    switched = _evaluate(
        _local(MONDAY, 0, 1), settings, sources={"workday": ON}, state=too_early.state
    )
    morning = _evaluate(
        _local(MONDAY, 6, 30), settings, sources={"workday": ON}, state=switched.state
    )

    assert too_early.day_type is DayType.WEEKEND
    assert too_early.day_type_latched is False
    assert too_early.morning_trigger == _local(MONDAY, 8, 30)
    assert _latched_dates(too_early) == [the_day_before]
    assert switched.day_type is DayType.WORKDAY
    assert switched.day_type_latched is False
    assert switched.morning_trigger == _local(MONDAY, 6, 30)
    assert switched.next_action == PlannedAction(
        _local(MONDAY, 6, 30), OPEN, ReasonCode.SCHEDULE_DAY
    )
    assert morning.part_of_day is PartOfDay.DAY
    assert morning.day_type_latched is True
    assert morning.state.latched_day_types == (LatchedDayType(MONDAY, DayType.WORKDAY),)


def _latched_dates(result: ScheduleResult) -> list[date]:
    return [latch.day for latch in result.state.latched_day_types]


def test_the_day_type_latches_at_the_morning_trigger_and_then_stays() -> None:
    """A source that changes in the middle of the day moves nothing after the fact."""
    night = _evaluate(
        _local(MONDAY, 0, 1), WITH_SOURCES, sources={"workday": ON, "holiday": OFF}
    )
    morning = _evaluate(
        _local(MONDAY, 6, 30),
        WITH_SOURCES,
        sources={"workday": ON, "holiday": OFF},
        state=night.state,
    )
    noon = _evaluate(
        _local(MONDAY, 12),
        WITH_SOURCES,
        sources={"workday": OFF, "holiday": ON},
        state=morning.state,
    )

    assert night.day_type_latched is False
    assert night.state.latched_day_types == ()
    assert morning.day_type_latched is True
    assert noon.day_type is DayType.WORKDAY
    assert noon.day_type_latched is True
    assert noon.morning_trigger == _local(MONDAY, 6, 30)
    assert noon.evening_trigger == _local(MONDAY, 20, 0)
    assert noon.state == morning.state


def test_an_input_that_comes_back_before_the_morning_trigger_is_used() -> None:
    """06:00 on a public holiday: the preview corrects itself, 09:00 fixes it."""
    missing = dict(MISSING)
    holiday: dict[str, AnySourceValue] = {"workday": OFF, "holiday": ON}
    night = _evaluate(_local(MONDAY, 0, 1), WITH_SOURCES, sources=missing)
    back = _evaluate(
        _local(MONDAY, 6), WITH_SOURCES, sources=holiday, state=night.state
    )
    still_night = _evaluate(
        _local(MONDAY, 7), WITH_SOURCES, sources=holiday, state=back.state
    )
    morning = _evaluate(
        _local(MONDAY, 9), WITH_SOURCES, sources=holiday, state=still_night.state
    )

    assert night.day_type is DayType.WORKDAY
    assert night.day_type_reason is ReasonCode.DAY_TYPE_FALLBACK
    assert night.next_action == PlannedAction(
        _local(MONDAY, 6, 30), OPEN, ReasonCode.SCHEDULE_DAY
    )
    assert back.day_type is DayType.HOLIDAY
    assert back.day_type_reason is None
    assert back.day_type_latched is False
    assert still_night.part_of_day is PartOfDay.NIGHT
    assert still_night.morning_trigger == _local(MONDAY, 9, 0)
    assert morning.part_of_day is PartOfDay.DAY
    assert morning.state.latched_day_types == (LatchedDayType(MONDAY, DayType.HOLIDAY),)


def test_after_the_morning_trigger_the_fallback_stays_for_the_date() -> None:
    """06:30 has passed without a value: the workday stands, and says why."""
    missing = dict(MISSING)
    passed = _evaluate(_local(MONDAY, 6, 30), WITH_SOURCES, sources=missing)
    back = _evaluate(
        _local(MONDAY, 8),
        WITH_SOURCES,
        sources={"workday": OFF, "holiday": ON},
        state=passed.state,
    )

    assert passed.day_type is DayType.WORKDAY
    assert passed.day_type_latched is True
    assert passed.state.latched_day_types == (
        LatchedDayType(MONDAY, DayType.WORKDAY, fallback=True),
    )
    assert back.day_type is DayType.WORKDAY
    assert back.day_type_reason is ReasonCode.DAY_TYPE_FALLBACK
    assert back.part_of_day is PartOfDay.DAY
    assert back.evening_trigger == _local(MONDAY, 20, 0)
    assert back.state == passed.state


def test_a_start_in_the_middle_of_the_day_latches_from_the_inputs() -> None:
    """No latch for the date and the morning trigger has passed: it is set at once."""
    result = _evaluate(
        _local(MONDAY, 12), WITH_SOURCES, sources={"workday": OFF, "holiday": ON}
    )

    assert result.day_type is DayType.HOLIDAY
    assert result.day_type_latched is True
    assert result.day_type_reason is None


def test_latches_are_kept_for_today_and_tomorrow_only() -> None:
    """Yesterday's latch is dropped; one for tomorrow is kept and used."""
    tuesday = MONDAY + timedelta(days=1)
    state = WindowState(
        latched_day_types=(
            LatchedDayType(MONDAY - timedelta(days=1), DayType.WEEKEND),
            LatchedDayType(tuesday, DayType.HOLIDAY),
        )
    )

    result = _evaluate(_local(MONDAY, 21), state=state)

    assert result.state.latched_day_types == (
        LatchedDayType(MONDAY, DayType.WORKDAY),
        LatchedDayType(tuesday, DayType.HOLIDAY),
    )
    assert result.next_action == PlannedAction(
        _local(tuesday, 9, 0), OPEN, ReasonCode.SCHEDULE_DAY
    )


def test_yesterdays_latch_is_kept_until_todays_is_set() -> None:
    """The night that is still running began with yesterday's evening trigger."""
    state = WindowState(latched_day_types=(LatchedDayType(SUNDAY, DayType.HOLIDAY),))
    monday = SUNDAY + timedelta(days=1)

    night = _evaluate(_local(monday, 3), state=state)
    morning = _evaluate(_local(monday, 6, 30), state=night.state)

    assert night.state == state
    assert night.part_of_day_since == _local(SUNDAY, 21, 30)
    assert morning.state.latched_day_types == (LatchedDayType(monday, DayType.WORKDAY),)
    assert morning.part_of_day_since == _local(monday, 6, 30)


# --- Since when the part of the day has been running ---------------------------------------------


@pytest.mark.parametrize(
    ("at", "since"),
    [
        (_local(MONDAY, 6, 30), _local(MONDAY, 6, 30)),
        (_local(MONDAY, 13), _local(MONDAY, 6, 30)),
        (_local(MONDAY, 20), _local(MONDAY, 20)),
        (_local(MONDAY, 23, 30), _local(MONDAY, 20)),
        (_local(MONDAY, 5), _local(MONDAY - timedelta(days=1), 21)),
        (_local(SATURDAY, 8), _local(FRIDAY, 20)),
    ],
    ids=[
        "at the morning trigger",
        "by day",
        "at the evening trigger",
        "late",
        "before the morning, after a weekend evening",
        "before a weekend morning, after a workday evening",
    ],
)
def test_the_part_of_the_day_began_at_its_boundary(
    at: datetime, since: datetime
) -> None:
    """The boundary's instant, whenever the evaluation takes place; never later than it."""
    result = _evaluate(at)

    assert result.part_of_day_since == since
    assert result.part_of_day_since <= result.evaluated_at == at


def test_a_moved_boundary_reports_the_instant_at_which_it_really_was() -> None:
    """Clamp and random offset move the morning; a late first evaluation changes nothing."""
    settings = _settings(
        workday=DayTriggers(_sun_event((time(5, 50), time(9, 0))), _fixed(20, 0)),
        random_offset=RANGE,
    )
    shortly_after = _evaluate(_local(MONDAY, 7), settings)
    much_later = _evaluate(_local(MONDAY, 15), settings)

    assert shortly_after.part_of_day_since == shortly_after.morning_trigger
    assert much_later.part_of_day_since == shortly_after.part_of_day_since
    assert _local(MONDAY, 5, 50) <= shortly_after.part_of_day_since
    assert shortly_after.part_of_day_since <= _local(MONDAY, 6, 15)


def test_a_night_begun_by_the_brightness_keeps_its_instant_until_the_morning() -> None:
    """17:10 yesterday is when this night began; after the morning it is dropped."""
    tuesday = MONDAY + timedelta(days=1)
    state = WindowState(
        latched_day_types=(LatchedDayType(MONDAY, DayType.WORKDAY),),
        evening_brightness_at=_local(MONDAY, 17, 10),
    )

    night = _evaluate(_local(tuesday, 2), BRIGHTNESS, sources=_lux(0), state=state)
    morning = _evaluate(
        _local(tuesday, 6, 30), BRIGHTNESS, sources=_lux(0), state=night.state
    )

    assert night.part_of_day_since == _local(MONDAY, 17, 10)
    assert night.evening_by_brightness is False
    assert night.evening_trigger == _local(tuesday, 18)
    assert night.state.evening_brightness_at == _local(MONDAY, 17, 10)
    assert night.recheck_at == _local(tuesday, 16)
    assert morning.state.evening_brightness_at is None


def test_a_result_cannot_be_built_with_a_recheck_that_is_not_in_the_future() -> None:
    """At or before the time of the snapshot is a bug, so it cannot be constructed."""
    result = _evaluate(_local(MONDAY, 17), BRIGHTNESS, sources=_lux(20))

    assert result.recheck_at is not None
    assert result.recheck_at > result.evaluated_at
    with pytest.raises(ValueError, match="strictly after"):
        replace(result, recheck_at=result.evaluated_at)
    with pytest.raises(ValueError, match="strictly after"):
        replace(result, recheck_at=result.evaluated_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match="begun in the future"):
        replace(result, part_of_day_since=result.evaluated_at + timedelta(seconds=1))


def test_a_recheck_is_strictly_in_the_future_or_none_at_every_minute() -> None:
    """A dark day, evaluated every minute: never a wake-up at or before now."""
    state = WindowState()
    rechecks = set()
    for minute in range(24 * 60):
        at = (_local(MONDAY, 0).astimezone(UTC) + timedelta(minutes=minute)).astimezone(
            ZONE
        )
        result = _evaluate(at, BRIGHTNESS, sources=_lux(20), state=state)
        state = result.state
        rechecks.add(result.recheck_at)
        assert result.recheck_at is None or result.recheck_at > result.evaluated_at

    assert rechecks == {None, _local(MONDAY, 16)}


# --- Daylight saving time and the change of day ------------------------------------------------


def _parts_every_five_minutes(
    settings: ScheduleSettings, first: date, days: int
) -> list[tuple[datetime, PartOfDay]]:
    start = local_instant(first, time(0, 0), ZONE)
    state = WindowState()
    parts = []
    for step in range(days * 24 * 12):
        at = (start + timedelta(minutes=5 * step)).astimezone(ZONE)
        result = _evaluate(at, settings, state=state)
        state = result.state
        parts.append((at.astimezone(UTC), result.part_of_day))
    return parts


def _changes(
    parts: list[tuple[datetime, PartOfDay]],
) -> list[tuple[datetime, PartOfDay]]:
    return [
        (at, part) for (_, before), (at, part) in pairwise(parts) if part is not before
    ]


@pytest.mark.parametrize(
    ("day", "morning_utc", "evening_utc"),
    [
        (CLOCKS_FORWARD, (1, 30), (18, 0)),
        (CLOCKS_BACK, (0, 30), (19, 0)),
    ],
    ids=["clocks forward", "clocks back"],
)
def test_a_clock_change_neither_skips_nor_doubles_a_part_of_the_day(
    day: date, morning_utc: tuple[int, int], evening_utc: tuple[int, int]
) -> None:
    """A morning at 02:30, in the skipped and in the repeated hour, comes once."""
    early = DayTriggers(_fixed(2, 30), _fixed(20, 0))
    settings = _settings(workday=early, weekend=early)
    before = day - timedelta(days=1)
    after = day + timedelta(days=1)

    changes = _changes(_parts_every_five_minutes(settings, before, 3))

    assert [part for _, part in changes] == [PartOfDay.DAY, PartOfDay.NIGHT] * 3
    assert changes[2] == (
        datetime.combine(day, time(*morning_utc), tzinfo=UTC),
        PartOfDay.DAY,
    )
    assert changes[3] == (
        datetime.combine(day, time(*evening_utc), tzinfo=UTC),
        PartOfDay.NIGHT,
    )
    assert changes[0][0] == local_instant(before, time(2, 30), ZONE)
    assert changes[4][0] == local_instant(after, time(2, 30), ZONE)


def test_the_second_pass_of_a_repeated_time_does_not_trigger_again() -> None:
    """02:15 of the second pass lies after 02:30 of the first: it is day already."""
    early = DayTriggers(_fixed(2, 30), _fixed(20, 0))
    settings = _settings(workday=early, weekend=early)
    first_pass = _local(CLOCKS_BACK, 2, 15)
    second_pass = first_pass.replace(fold=1)

    assert _evaluate(first_pass, settings).part_of_day is PartOfDay.NIGHT
    assert _evaluate(second_pass, settings).part_of_day is PartOfDay.DAY
    assert _evaluate(second_pass, settings).next_action == PlannedAction(
        _local(CLOCKS_BACK, 20), CLOSED, ReasonCode.SCHEDULE_NIGHT
    )


def test_the_change_of_day_changes_the_day_type_not_the_part_of_the_day() -> None:
    """Friday night runs into Saturday; the weekend morning comes at 08:30."""
    parts = _parts_every_five_minutes(SETTINGS, FRIDAY, 2)
    changes = _changes(parts)

    assert changes == [
        (_local(FRIDAY, 6, 30), PartOfDay.DAY),
        (_local(FRIDAY, 20, 0), PartOfDay.NIGHT),
        (_local(SATURDAY, 8, 30), PartOfDay.DAY),
        (_local(SATURDAY, 21, 0), PartOfDay.NIGHT),
    ]
    assert _evaluate(_local(SATURDAY, 0)).day_type is DayType.WEEKEND
    assert _evaluate(_local(SATURDAY, 7)).part_of_day is PartOfDay.NIGHT


# --- Next planned action -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("at", "expected"),
    [
        (
            _local(MONDAY, 3),
            PlannedAction(_local(MONDAY, 6, 30), OPEN, ReasonCode.SCHEDULE_DAY),
        ),
        (
            _local(MONDAY, 6, 30),
            PlannedAction(_local(MONDAY, 20), CLOSED, ReasonCode.SCHEDULE_NIGHT),
        ),
        (
            _local(MONDAY, 20),
            PlannedAction(
                _local(MONDAY + timedelta(days=1), 6, 30), OPEN, ReasonCode.SCHEDULE_DAY
            ),
        ),
        (
            _local(FRIDAY, 23, 59),
            PlannedAction(_local(SATURDAY, 8, 30), OPEN, ReasonCode.SCHEDULE_DAY),
        ),
        (
            _local(SATURDAY, 0),
            PlannedAction(_local(SATURDAY, 8, 30), OPEN, ReasonCode.SCHEDULE_DAY),
        ),
        (
            _local(SUNDAY, 21),
            PlannedAction(
                _local(SUNDAY + timedelta(days=1), 6, 30), OPEN, ReasonCode.SCHEDULE_DAY
            ),
        ),
        (
            _local(CLOCKS_FORWARD - timedelta(days=1), 22),
            PlannedAction(_local(CLOCKS_FORWARD, 8, 30), OPEN, ReasonCode.SCHEDULE_DAY),
        ),
    ],
    ids=[
        "before the morning",
        "at the morning",
        "at the evening",
        "across midnight into another day type",
        "at midnight",
        "from the weekend into the workday",
        "across the night of a clock change",
    ],
)
def test_next_planned_action(at: datetime, expected: PlannedAction) -> None:
    """Time, target and reason of the next change of the schedule."""
    action = _evaluate(at).next_action

    assert action == expected
    assert action is not None
    assert action.at.utcoffset() == timedelta(0)


def test_next_planned_action_with_a_seasonal_evening_position() -> None:
    """The target of tonight is the one of the season."""
    settings = _settings(
        targets={
            ScheduleProfile.DEFAULT: ScheduleTargets(OPEN, CLOSED, SUMMER_EVENING)
        },
        season_source="summer",
    )

    result = _evaluate(_local(MONDAY, 12), settings, sources={"summer": ON})

    assert result.next_action == PlannedAction(
        _local(MONDAY, 20), SUMMER_EVENING, ReasonCode.SCHEDULE_NIGHT
    )


def _swapping_settings() -> ScheduleSettings:
    """Return triggers one second apart, which a random offset can swap."""
    close = DayTriggers(
        Trigger(TriggerKind.FIXED_TIME, at=time(12, 0, 0)),
        Trigger(TriggerKind.FIXED_TIME, at=time(12, 0, 1)),
    )
    return _settings(workday=close, weekend=close, random_offset=timedelta(minutes=30))


def test_a_date_whose_triggers_were_swapped_has_no_day_and_is_skipped() -> None:
    """The evening never precedes the morning; the next action is on a later date."""
    settings = _swapping_settings()
    seed = next(
        seed
        for seed in range(1000)
        if random_offset(seed, WINDOW.window_id, MONDAY, Edge.EVENING, RANGE * 2)
        < random_offset(seed, WINDOW.window_id, MONDAY, Edge.MORNING, RANGE * 2)
    )

    parts = {
        _evaluate(_local(MONDAY, hour), settings, seed=seed).part_of_day
        for hour in range(24)
    }
    result = _evaluate(_local(MONDAY, 3), settings, seed=seed)

    assert parts == {PartOfDay.NIGHT}
    assert result.morning_trigger == result.evening_trigger
    assert result.next_action is not None
    assert result.next_action.reason is ReasonCode.SCHEDULE_DAY
    assert result.next_action.at >= _local(MONDAY + timedelta(days=1), 0)


def test_no_planned_action_within_the_days_that_are_searched() -> None:
    """A week and a day of swapped triggers: the schedule states that it sees none."""
    settings = _swapping_settings()

    def swapped_all_week(seed: int) -> bool:
        return all(
            random_offset(seed, WINDOW.window_id, day, Edge.EVENING, RANGE * 2)
            < random_offset(seed, WINDOW.window_id, day, Edge.MORNING, RANGE * 2)
            for day in (MONDAY + timedelta(days=ahead) for ahead in range(8))
        )

    seed = next(seed for seed in range(20000) if swapped_all_week(seed))

    assert _evaluate(_local(MONDAY, 3), settings, seed=seed).next_action is None


# --- Evening by brightness -------------------------------------------------------------------------

_SUNSET = DayTriggers(_fixed(6, 30), _sun_event(_LATE))
BRIGHTNESS = _settings(
    workday=_SUNSET,
    weekend=_SUNSET,
    holiday=_SUNSET,
    brightness_source="outdoor_brightness",
    brightness_threshold=50,
    brightness_delay=timedelta(minutes=10),
)


def _lux(value: float) -> dict[str, AnySourceValue]:
    return {"outdoor_brightness": SourceValue.of(value)}


def test_low_brightness_for_the_configured_time_begins_the_evening() -> None:
    """Dark at 17:00, ten minutes of delay: evening at 17:10 instead of 18:00."""
    dark = _evaluate(_local(MONDAY, 17), BRIGHTNESS, sources=_lux(20))
    waiting = _evaluate(
        _local(MONDAY, 17, 9), BRIGHTNESS, sources=_lux(20.5), state=dark.state
    )
    due = _evaluate(
        _local(MONDAY, 17, 12), BRIGHTNESS, sources=_lux(20), state=waiting.state
    )

    assert dark.part_of_day is PartOfDay.DAY
    assert dark.state.brightness_below_since == _local(MONDAY, 17)
    assert dark.recheck_at == _local(MONDAY, 17, 10)
    assert dark.next_action == PlannedAction(
        _local(MONDAY, 18), CLOSED, ReasonCode.SCHEDULE_NIGHT
    )
    assert waiting.part_of_day is PartOfDay.DAY
    assert waiting.state == dark.state
    assert due.part_of_day is PartOfDay.NIGHT
    assert due.evening_by_brightness is True
    assert due.evening_trigger == _local(MONDAY, 17, 10)
    assert due.recheck_at is None
    assert due.wish.reason is ReasonCode.SCHEDULE_NIGHT
    assert due.state.evening_brightness_at == _local(MONDAY, 17, 10)


@pytest.mark.parametrize(
    "sources",
    [
        _lux(900),
        {"outdoor_brightness": SourceValue.unavailable()},
        {"outdoor_brightness": SourceValue.unknown()},
        {},
    ],
    ids=["bright again", "unavailable", "unknown", "not in the snapshot"],
)
def test_an_evening_begun_by_the_brightness_stays(
    sources: dict[str, AnySourceValue],
) -> None:
    """Headlights or a source that drops out do not bring the day back."""
    state = WindowState(
        latched_day_types=(LatchedDayType(MONDAY, DayType.WORKDAY),),
        brightness_below_since=_local(MONDAY, 17),
        evening_brightness_at=_local(MONDAY, 17, 10),
    )

    result = _evaluate(_local(MONDAY, 17, 30), BRIGHTNESS, sources=sources, state=state)

    assert result.part_of_day is PartOfDay.NIGHT
    assert result.evening_by_brightness is True
    assert result.state.evening_brightness_at == _local(MONDAY, 17, 10)
    assert result.state.brightness_below_since is None


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        (SourceValue.unavailable(), ReasonCode.INPUT_UNAVAILABLE),
        (SourceValue.unknown(), ReasonCode.INPUT_UNKNOWN),
        (None, ReasonCode.INPUT_UNAVAILABLE),
        (SourceValue.of("dark"), ReasonCode.INPUT_UNKNOWN),
        (SourceValue.of(True), ReasonCode.INPUT_UNKNOWN),
    ],
    ids=["unavailable", "unknown", "not in the snapshot", "a text", "a boolean"],
)
def test_a_brightness_source_without_a_value_neither_triggers_nor_blocks(
    source: AnySourceValue | None, reason: ReasonCode
) -> None:
    """It is not 'dark', and the time-based trigger stays where it is."""
    sources = {} if source is None else {"outdoor_brightness": source}
    state = WindowState(brightness_below_since=_local(MONDAY, 16, 30))

    before = _evaluate(_local(MONDAY, 17, 30), BRIGHTNESS, sources=sources, state=state)
    after = _evaluate(
        _local(MONDAY, 18), BRIGHTNESS, sources=sources, state=before.state
    )

    assert before.part_of_day is PartOfDay.DAY
    assert before.evening_by_brightness is False
    assert before.brightness_reason is reason
    assert before.state.brightness_below_since is None
    assert before.state.evening_brightness_at is None
    assert before.recheck_at is None
    assert before.evening_trigger == _local(MONDAY, 18)
    assert after.part_of_day is PartOfDay.NIGHT
    assert after.evening_by_brightness is False


def test_the_brightness_triggers_only_inside_the_clamps() -> None:
    """A dark afternoon waits for 'not before'; after the time trigger nothing is left to do."""
    noon = _evaluate(_local(MONDAY, 13), BRIGHTNESS, sources=_lux(5))
    still_early = _evaluate(
        _local(MONDAY, 15, 59), BRIGHTNESS, sources=_lux(5), state=noon.state
    )
    at_the_clamp = _evaluate(
        _local(MONDAY, 16), BRIGHTNESS, sources=_lux(5), state=still_early.state
    )
    at_night = _evaluate(_local(MONDAY, 19), BRIGHTNESS, sources=_lux(5))

    assert noon.part_of_day is PartOfDay.DAY
    assert noon.recheck_at == _local(MONDAY, 16)
    assert still_early.part_of_day is PartOfDay.DAY
    assert at_the_clamp.part_of_day is PartOfDay.NIGHT
    assert at_the_clamp.evening_trigger == _local(MONDAY, 16)
    assert at_night.part_of_day is PartOfDay.NIGHT
    assert at_night.evening_by_brightness is False
    assert at_night.evening_trigger == _local(MONDAY, 18)
    assert at_night.recheck_at is None


def test_brightness_at_the_threshold_is_not_below_it() -> None:
    """Only a value below the threshold counts, and it has to last."""
    dark = _evaluate(_local(MONDAY, 17), BRIGHTNESS, sources=_lux(49.9))
    bright = _evaluate(
        _local(MONDAY, 17, 5), BRIGHTNESS, sources=_lux(50), state=dark.state
    )
    dark_again = _evaluate(
        _local(MONDAY, 17, 12), BRIGHTNESS, sources=_lux(10), state=bright.state
    )

    assert bright.state.brightness_below_since is None
    assert dark_again.part_of_day is PartOfDay.DAY
    assert dark_again.state.brightness_below_since == _local(MONDAY, 17, 12)
    assert dark_again.recheck_at == _local(MONDAY, 17, 22)


def test_yesterdays_brightness_evening_does_not_count_today() -> None:
    """The kept instant counts for the local date it lies on."""
    state = WindowState(evening_brightness_at=_local(MONDAY, 17, 10))
    tuesday = MONDAY + timedelta(days=1)

    result = _evaluate(_local(tuesday, 12), BRIGHTNESS, sources=_lux(900), state=state)

    assert result.part_of_day is PartOfDay.DAY
    assert result.evening_by_brightness is False
    assert result.state.evening_brightness_at is None


def test_without_a_brightness_source_its_state_is_dropped() -> None:
    """A feature that was switched off leaves nothing behind."""
    state = WindowState(
        brightness_below_since=_local(MONDAY, 17),
        evening_brightness_at=_local(MONDAY, 17, 10),
    )

    result = _evaluate(_local(MONDAY, 17, 30), state=state)

    assert result.part_of_day is PartOfDay.DAY
    assert result.brightness_reason is None
    assert result.state.brightness_below_since is None
    assert result.state.evening_brightness_at is None


# --- Seasonal evening position ------------------------------------------------------------------

SEASONAL_TARGETS = {
    ScheduleProfile.DEFAULT: ScheduleTargets(OPEN, CLOSED, SUMMER_EVENING)
}
BY_SOURCE = _settings(targets=SEASONAL_TARGETS, season_source="summer")
BY_DATE = _settings(
    targets=SEASONAL_TARGETS,
    summer_first_day=DayOfYear(5, 1),
    summer_last_day=DayOfYear(9, 21),
)
HELD_SUMMER = HeldInput(value=True, seen_at=_local(MONDAY - timedelta(days=30), 9))
HELD_WINTER = HeldInput(value=False, seen_at=_local(MONDAY - timedelta(days=30), 9))


@pytest.mark.parametrize(
    ("settings", "day", "sources", "held", "summer", "reason", "position"),
    [
        (BY_SOURCE, MONDAY, {"summer": ON}, None, True, None, SUMMER_EVENING),
        (BY_SOURCE, MONDAY, {"summer": OFF}, None, False, None, CLOSED),
        (BY_SOURCE, MONDAY, {"summer": OFF}, HELD_SUMMER, False, None, CLOSED),
        (
            BY_SOURCE,
            MONDAY,
            {"summer": SourceValue.unavailable()},
            HELD_SUMMER,
            True,
            ReasonCode.INPUT_HELD_LAST_KNOWN,
            SUMMER_EVENING,
        ),
        (
            BY_SOURCE,
            MONDAY,
            {"summer": SourceValue.unknown()},
            HELD_WINTER,
            False,
            ReasonCode.INPUT_HELD_LAST_KNOWN,
            CLOSED,
        ),
        (
            BY_SOURCE,
            MONDAY,
            {"summer": SourceValue.unavailable()},
            None,
            None,
            ReasonCode.INPUT_UNAVAILABLE,
            CLOSED,
        ),
        (
            replace(
                BY_DATE,
                season_source="summer",
            ),
            MONDAY,
            {"summer": SourceValue.unknown()},
            None,
            True,
            ReasonCode.INPUT_UNKNOWN,
            SUMMER_EVENING,
        ),
        (BY_DATE, MONDAY, {}, None, True, None, SUMMER_EVENING),
        (BY_DATE, MONDAY + timedelta(days=1), {}, None, False, None, CLOSED),
        (BY_DATE, date(2026, 5, 1), {}, None, True, None, SUMMER_EVENING),
        (BY_DATE, date(2026, 4, 30), {}, None, False, None, CLOSED),
        (SETTINGS, MONDAY, {}, HELD_SUMMER, None, None, CLOSED),
    ],
    ids=[
        "source on",
        "source off",
        "source off replaces the held value",
        "source unavailable, summer held",
        "source unknown, winter held",
        "source unavailable, nothing held",
        "source unknown, nothing held, dates decide",
        "last day of summer",
        "first day after summer",
        "first day of summer",
        "last day before summer",
        "no seasonal setup",
    ],
)
def test_the_evening_position_follows_the_season(  # noqa: PLR0913 - one row of the table
    *,
    settings: ScheduleSettings,
    day: date,
    sources: dict[str, AnySourceValue],
    held: HeldInput | None,
    summer: bool | None,
    reason: ReasonCode | None,
    position: Position,
) -> None:
    """A source, else its last known value, else a date range, else one position."""
    result = _evaluate(
        _local(day, 22), settings, sources=sources, state=WindowState(held_season=held)
    )

    assert result.summer is summer
    assert result.season_reason is reason
    assert result.wish.position == position
    assert result.wish.direction is Direction.LOWER_ONLY


def test_the_season_is_held_without_a_time_limit_and_renewed_on_change() -> None:
    """Seen in July, still held in September; a new value replaces it."""
    first = _evaluate(_local(date(2026, 7, 1), 12), BY_SOURCE, sources={"summer": ON})
    same = _evaluate(
        _local(date(2026, 7, 2), 12),
        BY_SOURCE,
        sources={"summer": ON},
        state=first.state,
    )
    changed = _evaluate(
        _local(MONDAY, 12), BY_SOURCE, sources={"summer": OFF}, state=same.state
    )

    assert first.state.held_season == HeldInput(
        value=True, seen_at=_local(date(2026, 7, 1), 12)
    )
    assert same.state.held_season == first.state.held_season
    assert changed.state.held_season == HeldInput(
        value=False, seen_at=_local(MONDAY, 12)
    )


def test_a_summer_that_runs_across_the_turn_of_the_year() -> None:
    """On the other half of the globe summer begins in December."""
    settings = _settings(
        targets=SEASONAL_TARGETS,
        summer_first_day=DayOfYear(12, 1),
        summer_last_day=DayOfYear(2, 28),
    )
    summers = {
        day: _evaluate(_local(day, 22), settings).summer
        for day in (
            date(2026, 11, 30),
            date(2026, 12, 1),
            date(2027, 1, 15),
            date(2027, 2, 28),
            date(2027, 3, 1),
        )
    }

    assert list(summers.values()) == [False, True, True, True, False]
