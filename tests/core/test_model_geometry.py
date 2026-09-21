"""The measurements of shading as values, as settings, and through the resolver."""

import dataclasses
from datetime import time, timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    GEOMETRY_FIELDS,
    MIN_CALIBRATION_SPAN,
    NO_CALIBRATION,
    CapabilityProfile,
    FunctionId,
    GeometryRuleError,
    GlassCalibration,
    MemberConfig,
    MemberGlass,
    Position,
    SettingsCombinationError,
    ShadingGeometrySettings,
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
    settings_from_stored,
    shading_geometry_keys,
)

MEMBERS = (
    MemberConfig(
        "cover.example_window",
        CapabilityProfile(
            supports_open_close=True,
            supports_set_position=True,
            supports_stop=True,
            reports_position=True,
            travel_time_up=timedelta(seconds=24),
            travel_time_down=timedelta(seconds=21),
        ),
    ),
)
HUGE = 10**400
VERTICAL = 90.0
DEFAULT_CAP = 2.0
FULL_RANGE = 100


def _window(**changes: Any) -> WindowConfig:
    return WindowConfig("window_example", MEMBERS, **changes)


# --- The view and its defaults ---------------------------------------------------------


def test_the_defaults_mean_no_measurements_and_the_simple_mode() -> None:
    """A window without measurements is the normal start; nothing is ``None``."""
    view = _window().geometry

    assert view == ShadingGeometrySettings()
    assert view.use_measurements is False
    assert view.orientation_known is False
    assert view.fixed_position == Position(30)
    assert view.pitch == VERTICAL
    assert view.amplification_cap == DEFAULT_CAP
    assert view.calibration == NO_CALIBRATION
    assert all(getattr(view, name) is not None for name in GEOMETRY_FIELDS)
    assert view.violated_rules == ()


def test_the_window_offers_its_measurements_as_one_value() -> None:
    """Every flat field reaches the view under its name without the prefix."""
    window = _window(
        shading_use_measurements=True,
        shading_orientation_known=True,
        shading_orientation=95.5,
        shading_view_left=40.0,
        shading_element_bottom=0.4,
        shading_calibration_seat=Position(12),
        shading_calibration_glass_top=Position(88),
    )

    assert window.geometry == ShadingGeometrySettings(
        use_measurements=True,
        orientation_known=True,
        orientation=95.5,
        view_left=40.0,
        element_bottom=0.4,
        calibration_seat=Position(12),
        calibration_glass_top=Position(88),
    )
    assert window.geometry.calibration == GlassCalibration(Position(12), Position(88))


def test_the_flat_fields_are_the_fields_of_the_view_with_the_prefix() -> None:
    """One list drives the fields, the view and the registry."""
    flat = {
        field.name
        for field in dataclasses.fields(WindowConfig)
        if field.name.startswith("shading_")
    }

    assert flat == {*shading_geometry_keys(), "shading_temperature_tiers"}
    assert shading_geometry_keys() == tuple(
        f"shading_{name}" for name in GEOMETRY_FIELDS
    )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("use_measurements", 1, TypeError),
        ("orientation_known", "yes", TypeError),
        ("fixed_position", 30, TypeError),
        ("orientation", 360.0, ValueError),
        ("orientation", -0.1, ValueError),
        ("orientation", True, TypeError),
        ("orientation", float("nan"), ValueError),
        ("orientation", HUGE, ValueError),
        ("view_left", 0.0, ValueError),
        ("view_left", 180.1, ValueError),
        ("view_right", 0, ValueError),
        ("view_right", float("inf"), ValueError),
        ("min_elevation", -1.0, ValueError),
        ("min_elevation", 90.5, ValueError),
        ("end_elevation", -0.5, ValueError),
        ("end_elevation", "10", TypeError),
        ("element_bottom", -0.01, ValueError),
        ("element_bottom", 100.5, ValueError),
        ("element_height", 0.0, ValueError),
        ("element_height", -HUGE, ValueError),
        ("depth", -1.0, ValueError),
        ("depth", None, TypeError),
        ("pitch", 90.1, ValueError),
        ("pitch", -5.0, ValueError),
        ("amplification_cap", 0.99, ValueError),
        ("amplification_cap", 10.5, ValueError),
        ("calibration_seat", 0, TypeError),
        ("calibration_glass_top", 100.0, TypeError),
    ],
)
def test_a_single_measurement_that_cannot_work_is_refused_and_named(
    field: str, value: Any, error: type[Exception]
) -> None:
    """By the view and by the window alike, with the field in the message."""
    with pytest.raises(error, match=field):
        ShadingGeometrySettings(**{field: value})
    with pytest.raises(error, match=field):
        _window(**{f"shading_{field}": value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("orientation", 0),
        ("orientation", 359.9),
        ("view_left", 180),
        ("min_elevation", 90),
        ("element_bottom", 0),
        ("depth", 0.0),
        ("pitch", 0),
        ("amplification_cap", 1),
        ("amplification_cap", 10.0),
    ],
)
def test_the_ends_of_the_ranges_are_allowed(field: str, value: float) -> None:
    """Whole numbers count as numbers."""
    arguments: dict[str, Any] = {field: value}

    assert getattr(ShadingGeometrySettings(**arguments), field) == value


def test_the_two_elevations_need_no_order() -> None:
    """Each is inherited on its own; a start needs the higher of the two."""
    low_end = ShadingGeometrySettings(min_elevation=12.0, end_elevation=5.0)
    high_end = ShadingGeometrySettings(min_elevation=5.0, end_elevation=8.0)

    assert low_end.start_elevation == low_end.min_elevation
    assert high_end.start_elevation == high_end.end_elevation
    assert high_end.violated_rules == ()


def test_the_calibration_of_the_window_must_be_in_order_and_apart() -> None:
    """The rule over two settings, named with the flat keys by the window."""
    with pytest.raises(GeometryRuleError) as view_error:
        ShadingGeometrySettings(
            calibration_seat=Position(80), calibration_glass_top=Position(20)
        )
    with pytest.raises(SettingsCombinationError) as error:
        _window(
            shading_calibration_seat=Position(60),
            shading_calibration_glass_top=Position(60 + MIN_CALIBRATION_SPAN - 1),
        )

    assert view_error.value.fields == ("calibration_seat", "calibration_glass_top")
    assert error.value.keys == (
        "shading_calibration_seat",
        "shading_calibration_glass_top",
    )
    assert _window(
        shading_calibration_seat=Position(60),
        shading_calibration_glass_top=Position(60 + MIN_CALIBRATION_SPAN),
    )


def test_single_values_are_checked_before_the_rules_over_several_settings() -> None:
    """A violated rule hides no invalid single value, of no view.

    The calibration points contradict each other. An invalid pitch is still
    what the window reports, and so is an invalid value of the schedule,
    whose view is built after the one of the geometry.
    """
    contradiction = {
        "shading_calibration_seat": Position(80),
        "shading_calibration_glass_top": Position(20),
    }

    with pytest.raises(ValueError, match="pitch") as pitch_error:
        _window(**contradiction, shading_pitch=120.0)
    with pytest.raises(ValueError, match="random offset") as schedule_error:
        _window(**contradiction, schedule_random_offset=timedelta(hours=1))

    assert not isinstance(pitch_error.value, SettingsCombinationError)
    assert not isinstance(schedule_error.value, SettingsCombinationError)


def test_a_violated_rule_of_the_schedule_is_still_reported() -> None:
    """The geometry in front of it changes nothing about the schedule's rules."""
    with pytest.raises(SettingsCombinationError) as error:
        _window(
            schedule_workday_evening_not_before=time(22, 30),
            schedule_workday_evening_not_after=time(21, 0),
        )

    assert "schedule_workday_evening_not_before" in error.value.keys


def test_two_refused_rules_are_reported_one_after_the_other() -> None:
    """The model names the first; the resolver pauses one function, then the other."""
    stored = {
        "shading_calibration_seat": 80,
        "shading_calibration_glass_top": 20,
        "schedule_workday_evening_not_before": "22:30",
        "schedule_workday_evening_not_after": "21:00",
        "frost_position": 70,
    }

    with pytest.raises(SettingsCombinationError) as error:
        _window(
            shading_calibration_seat=Position(80),
            shading_calibration_glass_top=Position(20),
            schedule_workday_evening_not_before=time(22, 30),
            schedule_workday_evening_not_after=time(21, 0),
        )
    resolution = _resolve(stored)

    assert error.value.keys == (
        "shading_calibration_seat",
        "shading_calibration_glass_top",
    )
    assert resolution.config is not None
    assert resolution.config.disabled_functions == frozenset(
        {FunctionId.SHADING, FunctionId.SCHEDULE}
    )
    assert resolution.config.frost_position == Position(70)
    assert {fault.key for fault in resolution.settings.faults} == set(stored) - {
        "frost_position"
    }


# --- Calibration and member glass ------------------------------------------------------


def test_no_calibration_is_the_full_range() -> None:
    """The defaults of a calibration."""
    assert GlassCalibration(FULLY_CLOSED, FULLY_OPEN) == NO_CALIBRATION
    assert NO_CALIBRATION.span == FULL_RANGE
    assert GlassCalibration(Position(12), Position(88)).span == 88 - 12


@pytest.mark.parametrize(
    ("seat", "top", "error", "named"),
    [
        (Position(50), Position(50), ValueError, "seat_position"),
        (Position(80), Position(20), ValueError, "glass_top_position"),
        (Position(45), Position(54), ValueError, "seat_position"),
        (12, Position(88), TypeError, "seat_position"),
        (Position(12), 88.0, TypeError, "glass_top_position"),
    ],
)
def test_a_calibration_out_of_order_or_too_close_is_refused_and_named(
    seat: Any, top: Any, error: type[Exception], named: str
) -> None:
    """The seating point is the smaller number, at least ten below the glass top."""
    with pytest.raises(error, match=named):
        GlassCalibration(seat, top)


@pytest.mark.parametrize(
    ("changes", "error", "named"),
    [
        ({"member_id": ""}, ValueError, "identifier"),
        ({"glass_height": 0.0}, ValueError, "glass_height"),
        ({"glass_height": -1.0}, ValueError, "glass_height"),
        ({"glass_height": 100.5}, ValueError, "glass_height"),
        ({"glass_height": float("nan")}, ValueError, "glass_height"),
        ({"glass_height": "1.2"}, TypeError, "glass_height"),
        ({"top_offset": -0.1}, ValueError, "top_offset"),
        ({"top_offset": HUGE}, ValueError, "top_offset"),
        ({"top_offset": False}, TypeError, "top_offset"),
        ({"calibration": (0, 100)}, TypeError, "calibration"),
    ],
)
def test_member_glass_that_cannot_work_is_refused_and_named(
    changes: dict[str, Any], error: type[Exception], named: str
) -> None:
    """The measurements of a member validate themselves."""
    arguments: dict[str, Any] = {"member_id": "cover.example_window"}
    arguments["glass_height"] = 1.2

    with pytest.raises(error, match=named):
        MemberGlass(**(arguments | changes))


def test_a_member_without_an_offset_has_offset_zero_and_no_calibration() -> None:
    """The side-by-side case is the default."""
    member = MemberGlass("cover.example_window", 1.2)

    assert member.top_offset == 0.0
    assert member.calibration == NO_CALIBRATION
    assert member.fits_into(1.2)
    assert not member.fits_into(1.19)
    assert MemberGlass("cover.example_lower", 0.6, 1.1).fits_into(1.7)


# --- The registry ----------------------------------------------------------------------

_KINDS = {
    "use_measurements": (SettingKind.BOOLEAN, True, True),
    "fixed_position": (SettingKind.NUMBER, 25, Position(25)),
    "orientation_known": (SettingKind.BOOLEAN, True, True),
    "orientation": (SettingKind.NUMBER, 95, 95.0),
    "view_left": (SettingKind.NUMBER, 40.5, 40.5),
    "view_right": (SettingKind.NUMBER, 75, 75.0),
    "min_elevation": (SettingKind.NUMBER, 12, 12.0),
    "end_elevation": (SettingKind.NUMBER, 0, 0.0),
    "element_bottom": (SettingKind.NUMBER, 0.85, 0.85),
    "element_height": (SettingKind.NUMBER, 1.3, 1.3),
    "depth": (SettingKind.NUMBER, 1, 1.0),
    "pitch": (SettingKind.NUMBER, 40, 40.0),
    "amplification_cap": (SettingKind.NUMBER, 3, 3.0),
    "calibration_seat": (SettingKind.NUMBER, 12, Position(12)),
    "calibration_glass_top": (SettingKind.NUMBER, 88, Position(88)),
}


def test_every_measurement_is_registered_with_its_kind_function_and_reader() -> None:
    """Shading pauses on a fault; none of them can be "none"; all are inherited."""
    assert set(_KINDS) == set(GEOMETRY_FIELDS)
    definitions = {entry.key: entry for entry in WINDOW_SETTINGS.definitions}
    defaults = ShadingGeometrySettings()
    for name, (kind, stored, value) in _KINDS.items():
        definition = definitions[f"shading_{name}"]

        assert definition.kind is kind, name
        assert definition.kind is not SettingKind.OPTIONAL_REFERENCE
        assert definition.function is FunctionId.SHADING, name
        assert definition.inheritable, name
        assert definition.requires is None, name
        assert definition.default == getattr(defaults, name), name
        parsed = definition.parse(stored)
        assert parsed == value, name
        assert type(parsed) is type(value), name


@pytest.mark.parametrize(
    ("key", "stored"),
    [
        ("shading_use_measurements", 1),
        ("shading_orientation_known", "true"),
        ("shading_orientation", "180"),
        ("shading_orientation", True),
        ("shading_depth", float("inf")),
        ("shading_pitch", HUGE),
        ("shading_fixed_position", 30.0),
        ("shading_fixed_position", 101),
        ("shading_calibration_seat", -1),
        ("shading_element_height", "__none__"),
    ],
)
def test_a_stored_value_the_shared_readers_refuse_is_a_fault(
    key: str, stored: Any
) -> None:
    """Nothing is read leniently, and no measurement can be "none"."""
    partial = settings_from_stored({key: stored}, WINDOW_SETTINGS)

    assert [fault.key for fault in partial.faults] == [key]
    assert partial.faults[0].problem in {
        SettingProblem.UNREADABLE,
        SettingProblem.NONE_NOT_ALLOWED,
    }


# --- Through the resolver --------------------------------------------------------------


def _stored(data: dict[str, Any]) -> Any:
    return settings_from_stored(data, WINDOW_SETTINGS)


def _resolve(
    window: dict[str, Any],
    house: dict[str, Any] | None = None,
    group: dict[str, Any] | None = None,
) -> Any:
    return resolve_window(
        window_id="window_example",
        members=MEMBERS,
        global_settings=_stored(house or {}),
        window_settings=_stored(window),
        group=None if group is None else GroupLevel("group_example", _stored(group)),
    )


def test_every_measurement_inherits_on_its_own() -> None:
    """House, group and window each set some of the measurements."""
    resolution = _resolve(
        {"shading_use_measurements": True, "shading_element_height": 1.4},
        house={"shading_depth": 1.0, "shading_amplification_cap": 3},
        group={
            "shading_orientation_known": True,
            "shading_orientation": 95,
            "shading_depth": 0.8,
        },
    )

    assert resolution.settings.faults == ()
    assert resolution.config is not None
    assert resolution.config.disabled_functions == frozenset()
    assert resolution.config.geometry == ShadingGeometrySettings(
        use_measurements=True,
        orientation_known=True,
        orientation=95.0,
        element_height=1.4,
        depth=0.8,
        amplification_cap=3.0,
    )
    levels = {key: value.level for key, value in resolution.settings.values.items()}
    assert levels["shading_depth"] is Level.GROUP
    assert levels["shading_amplification_cap"] is Level.GLOBAL
    assert levels["shading_element_height"] is Level.WINDOW
    assert levels["shading_pitch"] is Level.BUILT_IN


def test_a_window_without_stored_measurements_is_in_the_simple_mode() -> None:
    """Nothing stored, nothing faulty, nothing paused."""
    resolution = _resolve({})

    assert resolution.config is not None
    assert resolution.settings.faults == ()
    assert resolution.config.geometry == ShadingGeometrySettings()


def test_a_refused_combination_reports_its_keys_and_leaves_the_rest_alone() -> None:
    """The window's calibration points contradict each other; the rest stays.

    Each of the two values is fine on its own, and the house's seating point
    alone would be fine with the default; only together they are refused.
    """
    resolution = _resolve(
        {
            "shading_calibration_glass_top": 40,
            "shading_depth": 0.7,
            "frost_position": 70,
        },
        house={"shading_calibration_seat": 35},
    )
    faults = {fault.key: fault for fault in resolution.settings.faults}

    assert resolution.config is not None
    assert set(faults) == {"shading_calibration_seat", "shading_calibration_glass_top"}
    assert {fault.key: fault.level for fault in faults.values()} == {
        "shading_calibration_seat": Level.GLOBAL,
        "shading_calibration_glass_top": Level.WINDOW,
    }
    assert resolution.config.geometry.calibration == NO_CALIBRATION
    assert {fault.problem for fault in faults.values()} == {SettingProblem.COMBINATION}
    assert {fault.action for fault in faults.values()} == {
        FaultAction.FUNCTIONS_DISABLED
    }
    assert resolution.config.disabled_functions == frozenset({FunctionId.SHADING})
    assert resolution.config.frost_position == Position(70)
    assert resolution.config.shading_depth == pytest.approx(0.7)
    assert resolution.settings.values["shading_depth"].level is Level.WINDOW
    assert resolution.settings.values["frost_position"].level is Level.WINDOW


def test_a_faulty_measurement_pauses_shading_for_the_window_it_reaches() -> None:
    """The group's pitch is invalid: the inheriting window pauses shading only.

    A window of the same group with a sound pitch of its own is not reached,
    and the schedule and frost protection of both keep their values.
    """
    group = {"shading_pitch": 120, "frost_position": 80}
    inheriting = _resolve({}, group=group)
    with_own_value = _resolve({"shading_pitch": 40}, group=group)

    assert inheriting.config is not None
    assert inheriting.config.disabled_functions == frozenset({FunctionId.SHADING})
    assert inheriting.config.shading_pitch == VERTICAL
    assert inheriting.config.frost_position == Position(80)
    assert [
        (fault.key, fault.level, fault.problem, fault.action)
        for fault in inheriting.settings.faults
    ] == [
        (
            "shading_pitch",
            Level.GROUP,
            SettingProblem.INVALID,
            FaultAction.FUNCTIONS_DISABLED,
        )
    ]
    assert with_own_value.config is not None
    assert with_own_value.config.disabled_functions == frozenset()
    assert with_own_value.config.shading_pitch == pytest.approx(40.0)
    assert [fault.action for fault in with_own_value.settings.faults] == [
        FaultAction.NO_EFFECT
    ]
