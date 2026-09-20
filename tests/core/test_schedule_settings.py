"""The resolved settings of the schedule validate themselves on construction."""

from collections.abc import Callable
from datetime import UTC, date, time, timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.model import (
    DayType,
    Position,
    ScheduleProfile,
)
from custom_components.roller_shutter_suite.core.schedule import (
    MAX_RANDOM_OFFSET,
    DayOfYear,
    DayTriggers,
    ScheduleSettings,
    ScheduleTargets,
    Trigger,
    TriggerKind,
)

MORNING = Trigger(TriggerKind.FIXED_TIME, at=time(7, 0))
EVENING = Trigger(TriggerKind.FIXED_TIME, at=time(20, 0))
EVENING_WITH_CLAMPS = Trigger(
    TriggerKind.SUN_EVENT, not_before=time(16, 0), not_after=time(22, 0)
)
DAY = DayTriggers(MORNING, EVENING)
THRESHOLD = 50
TARGETS = {ScheduleProfile.DEFAULT: ScheduleTargets(Position(100), Position(0))}


def _settings(**changes: Any) -> ScheduleSettings:
    arguments: dict[str, Any] = {
        "workday": DAY,
        "weekend": DAY,
        "holiday": DAY,
        "targets": TARGETS,
    }
    return ScheduleSettings(**(arguments | changes))


# --- Triggers ------------------------------------------------------------------------


def test_each_kind_of_trigger_can_be_built() -> None:
    """A fixed time needs its time; the kinds of the sun need both clamps."""
    fixed = Trigger(TriggerKind.FIXED_TIME, at=time(6, 30))
    sun_event = Trigger(
        TriggerKind.SUN_EVENT,
        offset=timedelta(minutes=-20),
        not_before=time(6, 0),
        not_after=time(8, 0),
    )
    elevation = Trigger(
        TriggerKind.ELEVATION,
        elevation=-3,
        not_before=time(16, 0),
        not_after=time(22, 0),
    )

    assert (fixed.earliest, fixed.latest) == (time(6, 30), time(6, 30))
    assert (sun_event.earliest, sun_event.latest) == (time(6, 0), time(8, 0))
    assert (elevation.earliest, elevation.latest) == (time(16, 0), time(22, 0))
    assert fixed.fixed_time == time(6, 30)


def test_a_fixed_time_may_carry_clamps_around_it() -> None:
    """They matter with a random offset and for the brightness trigger."""
    trigger = Trigger(
        TriggerKind.FIXED_TIME,
        at=time(20, 0),
        not_before=time(17, 0),
        not_after=time(20, 15),
    )

    assert (trigger.earliest, trigger.latest) == (time(17, 0), time(20, 15))


def test_fields_of_another_kind_are_kept_and_ignored() -> None:
    """Switching the kind does not require clearing what was entered before."""
    trigger = Trigger(
        TriggerKind.FIXED_TIME, at=time(7, 0), offset=timedelta(hours=1), elevation=5.0
    )

    assert trigger.fixed_time == time(7, 0)


@pytest.mark.parametrize(
    ("build", "error", "message"),
    [
        (lambda: Trigger("fixed_time", at=time(7, 0)), TypeError, "TriggerKind"),  # type: ignore[arg-type]
        (lambda: Trigger(TriggerKind.FIXED_TIME), ValueError, "needs its time"),
        (
            lambda: Trigger(TriggerKind.FIXED_TIME, at="07:00"),  # type: ignore[arg-type]
            TypeError,
            "must be a time",
        ),
        (
            lambda: Trigger(TriggerKind.FIXED_TIME, at=time(7, 0, tzinfo=UTC)),
            ValueError,
            "carries no zone",
        ),
        (
            lambda: Trigger(TriggerKind.FIXED_TIME, at=time(7, 0), offset=30),  # type: ignore[arg-type]
            TypeError,
            "duration",
        ),
        (
            lambda: Trigger(TriggerKind.SUN_EVENT, not_before=time(6, 0)),
            ValueError,
            "needs 'not before' and 'not after'",
        ),
        (
            lambda: Trigger(TriggerKind.SUN_EVENT, not_after=time(8, 0)),
            ValueError,
            "needs 'not before' and 'not after'",
        ),
        (
            lambda: Trigger(
                TriggerKind.ELEVATION, not_before=time(6, 0), not_after=time(8, 0)
            ),
            ValueError,
            "needs its elevation",
        ),
        (
            lambda: Trigger(
                TriggerKind.ELEVATION,
                elevation=True,
                not_before=time(6, 0),
                not_after=time(8, 0),
            ),
            TypeError,
            "must be a number",
        ),
        (
            lambda: Trigger(
                TriggerKind.ELEVATION,
                elevation=91.0,
                not_before=time(6, 0),
                not_after=time(8, 0),
            ),
            ValueError,
            "within -90 and 90",
        ),
        (
            lambda: Trigger(
                TriggerKind.ELEVATION,
                elevation=float("nan"),
                not_before=time(6, 0),
                not_after=time(8, 0),
            ),
            ValueError,
            "within -90 and 90",
        ),
        (
            lambda: Trigger(
                TriggerKind.SUN_EVENT, not_before=time(9, 0), not_after=time(8, 0)
            ),
            ValueError,
            "must not lie after",
        ),
        (
            lambda: Trigger(
                TriggerKind.FIXED_TIME, at=time(7, 0), not_before=time(7, 30)
            ),
            ValueError,
            "must not lie after",
        ),
        (
            lambda: Trigger(
                TriggerKind.FIXED_TIME,
                at=time(9, 0),
                not_before=time(6, 0),
                not_after=time(8, 0),
            ),
            ValueError,
            "inside its clamps",
        ),
    ],
)
def test_a_trigger_that_cannot_work_is_refused(
    build: Callable[[], Trigger], error: type[Exception], message: str
) -> None:
    """An object that exists is valid."""
    with pytest.raises(error, match=message):
        build()


def test_only_a_fixed_time_trigger_has_a_fixed_time() -> None:
    """Asking a trigger of the sun for its fixed time is a fault of the caller."""
    with pytest.raises(ValueError, match="only a trigger of the kind 'fixed_time'"):
        _ = EVENING_WITH_CLAMPS.fixed_time


def test_the_morning_lies_before_the_evening() -> None:
    """The latest morning comes before the earliest evening, so a day has both parts."""
    overlapping = Trigger(
        TriggerKind.SUN_EVENT, not_before=time(6, 0), not_after=time(16, 0)
    )

    with pytest.raises(ValueError, match="latest morning"):
        DayTriggers(overlapping, EVENING_WITH_CLAMPS)
    with pytest.raises(ValueError, match="latest morning"):
        DayTriggers(EVENING, MORNING)
    with pytest.raises(TypeError, match="morning trigger"):
        DayTriggers("07:00", EVENING)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="evening trigger"):
        DayTriggers(MORNING, None)  # type: ignore[arg-type]


# --- Days of the year and targets -------------------------------------------------------


def test_day_of_year_is_a_calendar_day() -> None:
    """29 February is one; 30 February and month 13 are not."""
    assert DayOfYear(2, 29) == DayOfYear.of(date(2028, 2, 29))
    assert DayOfYear(4, 15) < DayOfYear(10, 1)
    with pytest.raises(ValueError, match="day"):
        DayOfYear(2, 30)
    with pytest.raises(ValueError, match="month"):
        DayOfYear(13, 1)
    with pytest.raises(TypeError, match="integers"):
        DayOfYear(4, 1.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="integers"):
        DayOfYear(True, 1)


def test_targets_choose_the_evening_position_by_season() -> None:
    """Without a summer position there is one evening position."""
    seasonal = ScheduleTargets(Position(100), Position(0), Position(30))
    plain = ScheduleTargets(Position(100), Position(0))

    assert seasonal.evening(summer=True) == Position(30)
    assert seasonal.evening(summer=False) == Position(0)
    assert seasonal.evening(summer=None) == Position(0)
    assert plain.evening(summer=True) == Position(0)


def test_targets_are_positions() -> None:
    """A plain number is not a position."""
    with pytest.raises(TypeError, match="morning_position"):
        ScheduleTargets(100, Position(0))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="evening_position"):
        ScheduleTargets(Position(100), 0)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="summer evening position"):
        ScheduleTargets(Position(100), Position(0), 30)  # type: ignore[arg-type]


# --- The settings as a whole ------------------------------------------------------------


def test_settings_are_immutable_and_compare_by_value() -> None:
    """The mapping of the targets is copied and frozen."""
    targets = dict(TARGETS)
    settings = _settings(targets=targets)
    targets.clear()

    assert settings == _settings()
    assert settings.targets_for(ScheduleProfile.DEFAULT).morning_position == Position(
        100
    )
    with pytest.raises(TypeError):
        settings.targets[ScheduleProfile.DEFAULT] = TARGETS[ScheduleProfile.DEFAULT]  # type: ignore[index]
    with pytest.raises(AttributeError):
        settings.random_offset = timedelta(minutes=5)  # type: ignore[misc]


def test_settings_defaults() -> None:
    """No source, no season, no brightness trigger, random offset off."""
    settings = _settings()

    assert settings.workday_source is None
    assert settings.holiday_source is None
    assert settings.season_source is None
    assert settings.summer_range is None
    assert settings.brightness_source is None
    assert settings.random_offset == timedelta(0)


def test_triggers_are_looked_up_by_day_type() -> None:
    """Each day type has its own pair of triggers."""
    weekend = DayTriggers(Trigger(TriggerKind.FIXED_TIME, at=time(8, 30)), EVENING)
    holiday = DayTriggers(Trigger(TriggerKind.FIXED_TIME, at=time(9, 0)), EVENING)
    settings = _settings(weekend=weekend, holiday=holiday)

    assert settings.triggers_for(DayType.WORKDAY) is DAY
    assert settings.triggers_for(DayType.WEEKEND) is weekend
    assert settings.triggers_for(DayType.HOLIDAY) is holiday


def test_summer_range_needs_both_days() -> None:
    """The first and the last day of summer belong together."""
    settings = _settings(
        summer_first_day=DayOfYear(5, 1), summer_last_day=DayOfYear(9, 30)
    )

    assert settings.summer_range == (DayOfYear(5, 1), DayOfYear(9, 30))
    with pytest.raises(ValueError, match="belong together"):
        _settings(summer_first_day=DayOfYear(5, 1))
    with pytest.raises(TypeError, match="summer_last_day"):
        _settings(summer_first_day=DayOfYear(5, 1), summer_last_day=(9, 30))


def test_random_offset_is_limited_to_thirty_minutes() -> None:
    """Default 0 means off; 30 minutes is the maximum."""
    assert _settings(random_offset=MAX_RANDOM_OFFSET).random_offset == timedelta(
        minutes=30
    )
    with pytest.raises(ValueError, match="0 to 30 minutes"):
        _settings(random_offset=timedelta(minutes=31))
    with pytest.raises(ValueError, match="0 to 30 minutes"):
        _settings(random_offset=timedelta(minutes=-1))
    with pytest.raises(TypeError, match="duration"):
        _settings(random_offset=15)


def test_a_brightness_source_needs_a_threshold_and_not_before() -> None:
    """The brightness may begin the evening only inside the clamps."""
    with_clamps = DayTriggers(MORNING, EVENING_WITH_CLAMPS)
    settings = _settings(
        workday=with_clamps,
        weekend=with_clamps,
        holiday=with_clamps,
        brightness_source="outdoor_brightness",
        brightness_threshold=THRESHOLD,
        brightness_delay=timedelta(minutes=10),
    )

    assert settings.brightness_threshold == THRESHOLD
    with pytest.raises(ValueError, match="needs a threshold"):
        _settings(brightness_source="outdoor_brightness")
    with pytest.raises(ValueError, match="the weekend lacks it"):
        _settings(
            workday=with_clamps,
            holiday=with_clamps,
            brightness_source="outdoor_brightness",
            brightness_threshold=50.0,
        )


@pytest.mark.parametrize(
    ("changes", "error", "message"),
    [
        ({"workday": "07:00"}, TypeError, "triggers of the workday"),
        ({"targets": {}}, ValueError, "lack the profile 'default'"),
        ({"targets": {"default": None}}, TypeError, "keyed by a ScheduleProfile"),
        (
            {"targets": {ScheduleProfile.DEFAULT: (100, 0)}},
            TypeError,
            "must be ScheduleTargets",
        ),
        ({"workday_source": 7}, TypeError, "workday_source"),
        ({"holiday_source": ""}, ValueError, "holiday_source"),
        ({"brightness_delay": 10}, TypeError, "duration"),
        ({"brightness_delay": timedelta(minutes=-1)}, ValueError, "not be negative"),
        ({"brightness_threshold": "dark"}, TypeError, "must be a number"),
        ({"brightness_threshold": True}, TypeError, "must be a number"),
        ({"brightness_threshold": float("inf")}, ValueError, "finite"),
    ],
)
def test_settings_that_cannot_work_are_refused(
    changes: dict[str, Any], error: type[Exception], message: str
) -> None:
    """Every part is checked where the settings are created."""
    with pytest.raises(error, match=message):
        _settings(**changes)
