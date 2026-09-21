"""The settings of the schedule: values, the view of the window, the registry, faults."""

import dataclasses
from datetime import UTC, time, timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.model import (
    MAX_RANDOM_OFFSET,
    SCHEDULE_DAY_TYPES,
    SCHEDULE_EDGES,
    TRIGGER_FIELDS,
    DayTriggers,
    DayType,
    FunctionId,
    Position,
    ScheduleProfile,
    ScheduleRuleError,
    ScheduleSettings,
    ScheduleTargets,
    SettingsCombinationError,
    Trigger,
    TriggerKind,
    WindowConfig,
)
from custom_components.roller_shutter_suite.core.settings import (
    WINDOW_SETTINGS,
    FaultAction,
    GroupLevel,
    Level,
    SettingKind,
    SettingProblem,
    resolve_window,
    schedule_trigger_keys,
    settings_from_stored,
)
from tests.core.schedule_kit import CONFIG, EARLY, LATE, config, fixed, sun_event

SCHEDULE_KEYS = tuple(
    key for key in WINDOW_SETTINGS.keys if key.startswith("schedule_")
)


# --- A trigger on its own ---------------------------------------------------------------


def test_clamps_apply_to_the_kinds_of_the_sun_only() -> None:
    """A fixed time ignores them; they are the fallback of the other two kinds."""
    at_seven = Trigger(
        TriggerKind.FIXED_TIME,
        time=time(7, 0),
        not_before=time(8, 0),
        not_after=time(6, 0),
    )
    sunrise = sun_event(EARLY, -20)

    assert at_seven.clamps_apply is False
    assert (at_seven.earliest, at_seven.latest) == (time(7, 0), time(7, 0))
    assert at_seven.clamps_in_disorder == ()
    assert sunrise.clamps_apply is True
    assert (sunrise.earliest, sunrise.latest) == EARLY
    assert sunrise.offset == timedelta(minutes=-20)


@pytest.mark.parametrize(
    ("change", "error", "message"),
    [
        ({"kind": "fixed_time"}, TypeError, "kind of a trigger"),
        ({"time": "07:00"}, TypeError, "must be a time"),
        ({"not_before": time(7, 0, tzinfo=UTC)}, ValueError, "carries no zone"),
        ({"not_after": None}, TypeError, "must be a time"),
        ({"offset_minutes": 30.0}, TypeError, "whole number of minutes"),
        ({"offset_minutes": True}, TypeError, "whole number of minutes"),
        ({"offset_minutes": 721}, ValueError, "within -720 and 720"),
        ({"offset_minutes": -721}, ValueError, "within -720 and 720"),
        ({"elevation": True}, TypeError, "must be a number"),
        ({"elevation": "low"}, TypeError, "must be a number"),
        ({"elevation": 91.0}, ValueError, "within -90 and 90"),
        ({"elevation": float("nan")}, ValueError, "finite"),
    ],
)
def test_a_single_value_of_a_trigger_that_cannot_work_is_refused(
    change: dict[str, Any], error: type[Exception], message: str
) -> None:
    """An object that exists is valid, field by field."""
    with pytest.raises(error, match=message):
        dataclasses.replace(sun_event(EARLY), **change)


def test_the_two_rules_over_several_settings_name_their_fields() -> None:
    """Clamps in order for the kinds of the sun; the morning before the evening."""
    disorder = dataclasses.replace(sun_event(EARLY), not_before=time(9, 30))
    late_morning = DayTriggers(fixed(21, 0), sun_event(LATE))
    overlap = DayTriggers(sun_event((time(6, 0), time(16, 0))), fixed(15, 0))

    assert disorder.clamps_in_disorder == ("kind", "not_before", "not_after")
    assert DayTriggers(fixed(7, 0), sun_event(LATE)).morning_not_before_evening == ()
    assert late_morning.morning_not_before_evening == (
        "morning_kind",
        "morning_time",
        "evening_kind",
        "evening_not_before",
    )
    assert overlap.morning_not_before_evening == (
        "morning_kind",
        "morning_not_after",
        "evening_kind",
        "evening_time",
    )
    with pytest.raises(TypeError, match="morning trigger"):
        DayTriggers("07:00", fixed(20, 0))  # type: ignore[arg-type]


def test_targets_choose_the_evening_position_by_season() -> None:
    """Without a season the regular evening position applies."""
    targets = ScheduleTargets(Position(100), Position(0), Position(30))

    assert targets.evening(summer=True) == Position(30)
    assert targets.evening(summer=False) == Position(0)
    assert targets.evening(summer=None) == Position(0)
    with pytest.raises(TypeError, match="evening_position_summer"):
        ScheduleTargets(Position(100), Position(0), 30)  # type: ignore[arg-type]


# --- The view of the window ---------------------------------------------------------------


def test_the_window_offers_its_schedule_as_one_value() -> None:
    """Flat fields in, the settings of the schedule out; the targets under the profile key."""
    settings = CONFIG.schedule

    assert isinstance(settings, ScheduleSettings)
    assert settings.enabled is True
    assert settings.triggers_for(DayType.WORKDAY).morning == fixed(6, 30)
    assert settings.triggers_for(DayType.WEEKEND).evening == fixed(21, 0)
    assert settings.triggers_for("holiday").morning == fixed(9, 0)
    assert set(settings.targets) == {ScheduleProfile.DEFAULT}
    assert settings.targets_for(ScheduleProfile.DEFAULT).morning_position == (
        Position(100)
    )
    assert settings.summer_range is None
    assert config(summer_by_date=True).schedule.summer_range == ((5, 1), (9, 30))
    with pytest.raises(TypeError):
        settings.targets[ScheduleProfile.DEFAULT] = None  # type: ignore[index]


def test_the_built_in_defaults_build_and_satisfy_every_rule() -> None:
    """A window nobody configured has a schedule that works."""
    members = CONFIG.members
    settings = WindowConfig("window_example", members).schedule

    assert settings.violated_rules == ()
    assert settings.random_offset == timedelta(0)
    assert settings.brightness_source is None
    for day_type in SCHEDULE_DAY_TYPES:
        day = settings.triggers_for(day_type)
        assert day.morning.latest < day.evening.earliest


@pytest.mark.parametrize(
    ("changes", "error", "message"),
    [
        ({"enabled": 1}, TypeError, "switch of the schedule"),
        ({"workday_source": 7}, TypeError, "workday_source"),
        ({"holiday_source": ""}, ValueError, "holiday_source"),
        ({"summer_by_date": "yes"}, TypeError, "summer by date"),
        ({"summer_first_day": "05-01"}, TypeError, "a month and a day"),
        ({"summer_first_day": (5, True)}, TypeError, "a month and a day"),
        ({"summer_last_day": (2, 29)}, ValueError, "exists in every year"),
        ({"summer_last_day": (13, 1)}, ValueError, "exists in every year"),
        ({"brightness_threshold": "dark"}, TypeError, "must be a number"),
        ({"brightness_threshold": float("inf")}, ValueError, "finite"),
        ({"brightness_delay": 10}, TypeError, "delay of the brightness"),
        ({"brightness_delay": timedelta(minutes=-1)}, ValueError, "not be negative"),
        ({"random_offset": 15}, TypeError, "random offset"),
        (
            {"random_offset": MAX_RANDOM_OFFSET + timedelta(seconds=1)},
            ValueError,
            "0 to 30 minutes",
        ),
        ({"random_offset": timedelta(minutes=-1)}, ValueError, "0 to 30 minutes"),
        ({"morning_position": 100}, TypeError, "morning_position"),
    ],
)
def test_a_single_value_of_the_schedule_that_cannot_work_is_refused(
    changes: dict[str, Any], error: type[Exception], message: str
) -> None:
    """Every field of the window is checked where the window is created."""
    with pytest.raises(error, match=message):
        config(**changes)


def test_settings_built_by_hand_are_checked_like_those_of_a_window() -> None:
    """The view is a value of its own; the simulation may build one directly."""
    wrong: Any = {ScheduleProfile.DEFAULT: (100, 0)}
    settings = CONFIG.schedule

    with pytest.raises(TypeError, match="triggers of the weekend"):
        dataclasses.replace(settings, weekend="08:30")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="key of the targets"):
        dataclasses.replace(settings, targets={"default": None})  # type: ignore[dict-item]
    with pytest.raises(TypeError, match="targets of a profile"):
        dataclasses.replace(settings, targets=wrong)
    with pytest.raises(ValueError, match="lack the profile 'default'"):
        dataclasses.replace(settings, targets={})
    with pytest.raises(ScheduleRuleError, match="latest morning") as refused:
        dataclasses.replace(settings, holiday=DayTriggers(fixed(22, 0), fixed(21, 0)))
    assert refused.value.fields == (
        "holiday_morning_kind",
        "holiday_morning_time",
        "holiday_evening_kind",
        "holiday_evening_time",
    )


# --- Rules over several settings, raised by the window --------------------------------------


def test_clamps_in_disorder_name_the_flat_keys_they_concern() -> None:
    """Each value alone is fine; together they are refused, with their keys."""
    with pytest.raises(SettingsCombinationError, match="not before") as refused:
        config(
            weekend=DayTriggers(
                fixed(8, 30),
                dataclasses.replace(sun_event(LATE), not_before=time(22, 30)),
            )
        )

    assert refused.value.keys == (
        "schedule_weekend_evening_kind",
        "schedule_weekend_evening_not_before",
        "schedule_weekend_evening_not_after",
    )


def test_a_morning_that_is_not_before_the_evening_names_the_flat_keys() -> None:
    """The keys are those in use: the time of a fixed trigger, else the clamp."""
    with pytest.raises(SettingsCombinationError, match="latest morning") as refused:
        config(
            workday=DayTriggers(sun_event((time(6, 0), time(17, 0))), sun_event(LATE))
        )

    assert refused.value.keys == (
        "schedule_workday_morning_kind",
        "schedule_workday_morning_not_after",
        "schedule_workday_evening_kind",
        "schedule_workday_evening_not_before",
    )


def test_single_values_are_checked_before_the_rules_over_several_settings() -> None:
    """A combination that trips must not hide an invalid single value."""
    with pytest.raises(ValueError, match="0 to 30 minutes") as refused:
        config(
            workday=DayTriggers(fixed(22, 0), fixed(21, 0)),
            random_offset=timedelta(hours=1),
        )

    assert not isinstance(refused.value, SettingsCombinationError)


# --- The registry ------------------------------------------------------------------------------

_KIND_OF_FIELD = {
    "kind": SettingKind.ENUMERATION,
    "time": SettingKind.TIME,
    "offset_minutes": SettingKind.NUMBER,
    "elevation": SettingKind.NUMBER,
    "not_before": SettingKind.TIME,
    "not_after": SettingKind.TIME,
}

_STORED_FORM: dict[str, tuple[Any, Any]] = {
    "kind": ("elevation", TriggerKind.ELEVATION),
    "time": ("06:45", time(6, 45)),
    "offset_minutes": (-20, -20),
    "elevation": (-3.5, -3.5),
    "not_before": ("05:30:15", time(5, 30, 15)),
    "not_after": ("23:00", time(23, 0)),
}


def test_every_trigger_setting_is_registered_with_its_kind_and_reader() -> None:
    """Day type by edge by field: thirty-six entries, generated, none forgotten."""
    definitions = {entry.key: entry for entry in WINDOW_SETTINGS.definitions}
    expected = [
        (f"schedule_{day_type}_{edge}_{name}", name)
        for day_type in SCHEDULE_DAY_TYPES
        for edge in SCHEDULE_EDGES
        for name in TRIGGER_FIELDS
    ]

    assert schedule_trigger_keys() == tuple(key for key, _ in expected)
    assert len(expected) == 3 * 2 * 6
    for key, name in expected:
        definition = definitions[key]
        stored, value = _STORED_FORM[name]
        assert definition.kind is _KIND_OF_FIELD[name], key
        assert definition.function is FunctionId.SCHEDULE, key
        assert definition.inheritable is True, key
        assert definition.parse(stored) == value, key
        assert definition.default == getattr(WindowConfig("w", CONFIG.members), key)


@pytest.mark.parametrize(
    ("key", "kind", "stored", "value"),
    [
        ("schedule_enabled", SettingKind.BOOLEAN, False, False),
        ("schedule_morning_position", SettingKind.NUMBER, 80, Position(80)),
        ("schedule_evening_position", SettingKind.NUMBER, 10, Position(10)),
        ("schedule_evening_position_summer", SettingKind.NUMBER, 30, Position(30)),
        (
            "schedule_workday_source",
            SettingKind.OPTIONAL_REFERENCE,
            "binary_sensor.example_workday",
            "binary_sensor.example_workday",
        ),
        (
            "schedule_holiday_source",
            SettingKind.OPTIONAL_REFERENCE,
            "calendar.example_holidays",
            "calendar.example_holidays",
        ),
        (
            "schedule_season_source",
            SettingKind.OPTIONAL_REFERENCE,
            "input_boolean.example_summer",
            "input_boolean.example_summer",
        ),
        ("schedule_summer_by_date", SettingKind.BOOLEAN, True, True),
        ("schedule_summer_first_day", SettingKind.DAY_OF_YEAR, "04-15", (4, 15)),
        ("schedule_summer_last_day", SettingKind.DAY_OF_YEAR, "10-01", (10, 1)),
        (
            "schedule_brightness_source",
            SettingKind.OPTIONAL_REFERENCE,
            "sensor.example_brightness",
            "sensor.example_brightness",
        ),
        ("schedule_brightness_threshold", SettingKind.NUMBER, 35, 35.0),
        (
            "schedule_brightness_delay",
            SettingKind.DURATION,
            900,
            timedelta(minutes=15),
        ),
        ("schedule_random_offset", SettingKind.DURATION, 600, timedelta(minutes=10)),
    ],
)
def test_the_other_settings_of_the_schedule_are_registered(
    key: str, kind: SettingKind, stored: Any, value: Any
) -> None:
    """Kind, function and the shared reader of every one of them."""
    definition = next(
        entry for entry in WINDOW_SETTINGS.definitions if entry.key == key
    )

    assert definition.kind is kind
    assert definition.function is FunctionId.SCHEDULE
    assert definition.parse(stored) == value


def test_the_two_lists_above_are_all_settings_of_the_schedule() -> None:
    """Whoever adds a setting of the schedule adds it to one of the two tests."""
    listed = {
        *schedule_trigger_keys(),
        "schedule_enabled",
        "schedule_profile",
        "schedule_morning_position",
        "schedule_evening_position",
        "schedule_evening_position_summer",
        "schedule_workday_source",
        "schedule_holiday_source",
        "schedule_season_source",
        "schedule_summer_by_date",
        "schedule_summer_first_day",
        "schedule_summer_last_day",
        "schedule_brightness_source",
        "schedule_brightness_threshold",
        "schedule_brightness_delay",
        "schedule_random_offset",
    }

    assert set(SCHEDULE_KEYS) == listed


@pytest.mark.parametrize(
    ("key", "stored"),
    [
        ("schedule_workday_morning_time", "6:30"),
        ("schedule_workday_morning_time", "06:30+01:00"),
        ("schedule_workday_evening_offset_minutes", 12.5),
        ("schedule_workday_evening_offset_minutes", "30"),
        ("schedule_weekend_evening_kind", "sunset"),
        ("schedule_summer_first_day", "02-29"),
        ("schedule_summer_last_day", "9-30"),
        ("schedule_brightness_delay", -1),
        ("schedule_random_offset", "00:10"),
        ("schedule_morning_position", 101),
    ],
)
def test_a_stored_value_the_shared_readers_refuse_is_a_fault(
    key: str, stored: Any
) -> None:
    """Nothing is read leniently: a refused value is reported, not guessed."""
    partial = settings_from_stored({key: stored}, WINDOW_SETTINGS)

    assert [fault.key for fault in partial.faults] == [key]
    assert partial.faults[0].problem is SettingProblem.UNREADABLE


# --- Faults through the resolver -------------------------------------------------------------------


def _stored(data: dict[str, Any]) -> Any:
    return settings_from_stored(data, WINDOW_SETTINGS)


def _resolve(
    window: dict[str, Any],
    house: dict[str, Any] | None = None,
    group: dict[str, Any] | None = None,
) -> Any:
    return resolve_window(
        window_id="window_example",
        members=CONFIG.members,
        global_settings=_stored(house or {}),
        window_settings=_stored(window),
        group=None if group is None else GroupLevel("group_example", _stored(group)),
    )


def test_a_refused_combination_reports_its_keys_and_leaves_the_rest_alone() -> None:
    """The window's own clamps contradict each other; its own frost position stays."""
    resolution = _resolve(
        {
            "schedule_workday_evening_not_before": "22:30",
            "schedule_workday_evening_not_after": "21:00",
            "schedule_morning_position": 80,
            "frost_position": 70,
        }
    )
    faults = {fault.key: fault for fault in resolution.settings.faults}

    assert resolution.config is not None
    assert set(faults) == {
        "schedule_workday_evening_not_before",
        "schedule_workday_evening_not_after",
    }
    assert {fault.problem for fault in faults.values()} == {SettingProblem.COMBINATION}
    assert {fault.level for fault in faults.values()} == {Level.WINDOW}
    assert {fault.action for fault in faults.values()} == {
        FaultAction.FUNCTIONS_DISABLED
    }
    assert resolution.config.disabled_functions == frozenset({FunctionId.SCHEDULE})
    assert resolution.config.frost_position == Position(70)
    assert resolution.settings.values["frost_position"].level is Level.WINDOW
    assert resolution.settings.values["schedule_morning_position"].level is (
        Level.WINDOW
    )


def test_a_faulty_schedule_setting_pauses_the_schedule_for_the_window_it_reaches() -> (
    None
):
    """The group's morning time is unreadable: the window that inherits it pauses.

    A window of the same group with a sound own value is not reached, and
    neither loses anything else: frost protection keeps its values.
    """
    group = {"schedule_workday_morning_time": "half past six", "frost_position": 80}
    inheriting = _resolve({}, group=group)
    with_own_value = _resolve({"schedule_workday_morning_time": "06:15"}, group=group)

    assert inheriting.config is not None
    assert inheriting.config.disabled_functions == frozenset({FunctionId.SCHEDULE})
    assert [
        (fault.key, fault.level, fault.problem, fault.action)
        for fault in inheriting.settings.faults
    ] == [
        (
            "schedule_workday_morning_time",
            Level.GROUP,
            SettingProblem.UNREADABLE,
            FaultAction.FUNCTIONS_DISABLED,
        )
    ]
    assert inheriting.config.frost_position == Position(80)
    assert with_own_value.config is not None
    assert with_own_value.config.disabled_functions == frozenset()
    assert with_own_value.config.schedule_workday_morning_time == time(6, 15)
    assert [fault.action for fault in with_own_value.settings.faults] == [
        FaultAction.NO_EFFECT
    ]


def test_a_single_value_the_window_refuses_pauses_the_schedule_too() -> None:
    """Read, but refused by the rules of the window: a random offset of an hour."""
    resolution = _resolve({"schedule_random_offset": 3600})

    assert resolution.config is not None
    assert resolution.config.disabled_functions == frozenset({FunctionId.SCHEDULE})
    assert resolution.config.schedule_random_offset == timedelta(0)
    assert [(fault.key, fault.problem) for fault in resolution.settings.faults] == [
        ("schedule_random_offset", SettingProblem.INVALID)
    ]


def test_every_schedule_setting_inherits_on_its_own() -> None:
    """House, group and window each set one field of the same trigger."""
    resolution = _resolve(
        {"schedule_workday_morning_time": "06:10"},
        house={"schedule_workday_morning_kind": "fixed_time"},
        group={"schedule_workday_morning_not_after": "08:00"},
    )

    assert resolution.config is not None
    assert resolution.settings.faults == ()
    assert resolution.config.schedule.workday.morning == Trigger(
        TriggerKind.FIXED_TIME,
        time=time(6, 10),
        not_before=time(6, 0),
        not_after=time(8, 0),
    )
