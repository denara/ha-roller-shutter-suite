"""The sun relative to a window: horizontal angle, field of view, elevation, glass."""

from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.geometry import (
    GRAZING,
    SunExclusion,
    SunOnWindow,
    horizontal_angle,
    incidence,
    sun_on_window,
)
from custom_components.roller_shutter_suite.core.model import (
    ShadingGeometrySettings,
    SunPosition,
)

ON = None
SMALLEST_ANGLE_OF_INTEREST = 1e-6
LEFT = SunExclusion.LEFT_OF_VIEW
RIGHT = SunExclusion.RIGHT_OF_VIEW
BEHIND = SunExclusion.BEHIND_GLASS


def _facing(orientation: float, **changes: Any) -> ShadingGeometrySettings:
    return ShadingGeometrySettings(
        orientation_known=True, orientation=orientation, **changes
    )


# --- The horizontal angle: clockwise from north, positive is to the right ---------------


@pytest.mark.parametrize(
    ("sun_azimuth", "orientation", "expected"),
    [
        (180.0, 180.0, 0.0),
        (225.0, 180.0, 45.0),
        (135.0, 180.0, -45.0),
        (10.0, 350.0, 20.0),
        (350.0, 10.0, -20.0),
        (0.0, 0.0, 0.0),
        (359.0, 0.0, -1.0),
        (1.0, 0.0, 1.0),
        (90.0, 270.0, 180.0),
        (270.0, 90.0, 180.0),
        (269.0, 90.0, 179.0),
        (271.0, 90.0, -179.0),
    ],
)
def test_the_horizontal_angle_wraps_around_north(
    sun_azimuth: float, orientation: float, expected: float
) -> None:
    """More than -180, at most 180; straight behind counts as +180."""
    assert horizontal_angle(sun_azimuth, orientation) == pytest.approx(expected)


def test_positive_means_to_the_right_seen_from_inside_looking_out() -> None:
    """Looking out of a south window, the west is on the right hand.

    An azimuth grows clockwise from north: south is 180, south-west 225. A
    person who looks south has the west to the right. So the afternoon sun
    in the south-west is to the right, and the angle is positive.
    """
    south, south_west, south_east = 180.0, 225.0, 135.0

    assert horizontal_angle(south_west, south) > 0
    assert horizontal_angle(south_east, south) < 0
    # The same for a window that looks east: the south is to its right.
    assert horizontal_angle(180.0, 90.0) > 0


# --- Field of view for every quarter, with different limits ----------------------------


@pytest.mark.parametrize("orientation", [0.0, 90.0, 180.0, 270.0, 350.0, 5.0])
@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (0.0, ON),
        (-30.0, ON),
        (-30.5, LEFT),
        (-89.0, LEFT),
        (60.0, ON),
        (60.5, RIGHT),
        (120.0, RIGHT),
        (180.0, RIGHT),
        (-179.0, LEFT),
    ],
)
def test_the_field_of_view_has_its_own_limit_on_each_side(
    orientation: float, offset: float, expected: SunExclusion | None
) -> None:
    """30 degrees to the left, 60 to the right; a limit itself is inside.

    The same offsets are asked for windows that face every quarter and two
    that look across north, so the wrap-around is part of every row.
    """
    settings = _facing(orientation, view_left=30.0, view_right=60.0)
    sun = SunPosition((orientation + offset) % 360.0, 35.0)

    result = sun_on_window(sun, settings)

    assert result.exclusion is expected
    assert result.on_window is (expected is None)
    assert result.horizontal_angle == pytest.approx(offset)


def test_a_window_across_north_sees_the_sun_on_both_sides_of_north() -> None:
    """Facing 350 with 25 degrees to each side: from 325 over north to 15."""
    settings = _facing(350.0, view_left=25.0, view_right=25.0)

    def exclusion(azimuth: float) -> SunExclusion | None:
        return sun_on_window(SunPosition(azimuth, 20.0), settings).exclusion

    assert [exclusion(a) for a in (325.0, 340.0, 359.9, 0.0, 15.0)] == [ON] * 5
    assert exclusion(324.0) is LEFT
    assert exclusion(16.0) is RIGHT


# --- Elevation limits --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("elevation", "exclusion", "start"),
    [
        (-10.0, SunExclusion.BELOW_HORIZON, False),
        (0.0, SunExclusion.BELOW_HORIZON, False),
        (4.9, SunExclusion.BELOW_END_ELEVATION, False),
        (5.0, None, False),
        (11.9, None, False),
        (12.0, None, True),
        (60.0, None, True),
    ],
)
def test_the_end_elevation_excludes_and_the_minimum_elevation_permits_the_start(
    elevation: float, exclusion: SunExclusion | None, start: bool
) -> None:
    """End 5, start 12: between them the sun is on the window, but nothing starts."""
    settings = _facing(180.0, min_elevation=12.0, end_elevation=5.0)

    result = sun_on_window(SunPosition(180.0, elevation), settings)

    assert result.exclusion is exclusion
    assert result.start_permitted is start


def test_the_elevation_is_judged_before_the_field_of_view() -> None:
    """The first reason in the order of the enumeration is the one reported."""
    settings = _facing(180.0, view_left=10.0, view_right=10.0, end_elevation=5.0)

    assert (
        sun_on_window(SunPosition(0.0, -3.0), settings).exclusion
        is SunExclusion.BELOW_HORIZON
    )
    assert (
        sun_on_window(SunPosition(0.0, 3.0), settings).exclusion
        is SunExclusion.BELOW_END_ELEVATION
    )
    assert list(SunExclusion) == [
        SunExclusion.ORIENTATION_UNKNOWN,
        SunExclusion.BELOW_HORIZON,
        SunExclusion.BELOW_END_ELEVATION,
        LEFT,
        RIGHT,
        BEHIND,
    ]


# --- The plane of the glass ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("offset", "elevation", "expected"),
    [
        (89.0, 30.0, ON),
        (90.0, 30.0, BEHIND),
        (-90.0, 30.0, BEHIND),
        (135.0, 30.0, BEHIND),
        (180.0, 60.0, BEHIND),
        (0.0, 90.0, BEHIND),
        (0.0, 89.9, ON),
    ],
)
def test_vertical_glass_is_not_reached_at_and_beyond_the_facade_plane(
    offset: float, elevation: float, expected: SunExclusion | None
) -> None:
    """Also with a field of view of 180 degrees, and with the sun in the zenith."""
    settings = _facing(200.0, view_left=180.0, view_right=180.0)
    sun = SunPosition((200.0 + offset) % 360.0, elevation)

    assert sun_on_window(sun, settings).exclusion is expected


@pytest.mark.parametrize(
    ("offset", "elevation", "expected"),
    [
        (0.0, 30.0, ON),
        (90.0, 30.0, ON),
        (180.0, 60.0, ON),
        (180.0, 40.0, BEHIND),
        (180.0, 39.0, BEHIND),
        (180.0, 41.0, ON),
        (0.0, 90.0, ON),
    ],
)
def test_tilted_glass_is_reached_by_a_high_sun_from_behind_the_ridge(
    offset: float, elevation: float, expected: SunExclusion | None
) -> None:
    """A pitch of 40 degrees: from straight behind, the sun has to stand above 40.

    At exactly 40 it shines along the glass, which is not "onto" it.
    """
    settings = _facing(200.0, view_left=180.0, view_right=180.0, pitch=40.0)
    sun = SunPosition((200.0 + offset) % 360.0, elevation)

    assert sun_on_window(sun, settings).exclusion is expected


def test_the_incidence_is_the_cosine_between_the_sun_and_the_normal() -> None:
    """Exact in the cases that matter: straight ahead, the plane, the zenith."""
    assert incidence(0.0, 0.0, 90.0) == 1.0
    assert incidence(30.0, 90.0, 90.0) == 0.0
    assert incidence(90.0, 0.0, 90.0) == 0.0
    assert incidence(90.0, 123.0, 0.0) == 1.0
    assert incidence(50.0, 0.0, 40.0) == pytest.approx(1.0)
    assert incidence(60.0, 60.0, 90.0) == pytest.approx(0.25)
    assert 0 < GRAZING < SMALLEST_ANGLE_OF_INTEREST


# --- Without a known orientation ----------------------------------------------------------


@pytest.mark.parametrize("azimuth", [0.0, 90.0, 180.0, 270.0])
@pytest.mark.parametrize("elevation", [-20.0, 0.0, 3.0, 30.0, 90.0])
def test_without_a_known_orientation_nobody_can_say_that_the_sun_is_on_the_window(
    azimuth: float, elevation: float
) -> None:
    """Shading needs the orientation; nothing is assumed in its place.

    The number that stands in the field ``orientation`` does not count while
    the switch is off: it is the built-in default, not a statement. Assuming
    the sun straight ahead instead would shade a north window in every sun.
    """
    settings = ShadingGeometrySettings(orientation=180.0, end_elevation=5.0)

    result = sun_on_window(SunPosition(azimuth, elevation), settings)

    assert not result.on_window
    assert not result.start_permitted
    assert result.exclusion is SunExclusion.ORIENTATION_UNKNOWN
    assert result.horizontal_angle is None


# --- The result type ---------------------------------------------------------------------


def test_the_result_survives_plain_data() -> None:
    """With and without an exclusion, with and without an angle."""
    for value in (
        SunOnWindow(True, None, True, -12.5),
        SunOnWindow(True, None, False, 0.0),
        SunOnWindow(False, SunExclusion.ORIENTATION_UNKNOWN, False, None),
        SunOnWindow(False, RIGHT, False, 180.0),
    ):
        assert SunOnWindow.from_data(value.to_data()) == value


@pytest.mark.parametrize(
    "arguments",
    [
        (True, RIGHT, False, 10.0),
        (False, None, False, 10.0),
        (False, LEFT, True, -100.0),
        (True, None, True, None),
        (False, RIGHT, False, None),
        (False, SunExclusion.ORIENTATION_UNKNOWN, False, 10.0),
        (True, None, True, 180.5),
        (True, None, True, -180.0),
        (True, None, True, "10"),
        (1, None, True, 10.0),
        (True, "left_of_view", True, 10.0),
    ],
)
def test_a_result_that_contradicts_itself_is_refused(arguments: Any) -> None:
    """An object that exists is valid."""
    with pytest.raises((TypeError, ValueError)):
        SunOnWindow(*arguments)


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"on_window": True},
        {
            "on_window": True,
            "exclusion": None,
            "start_permitted": True,
            "horizontal_angle": float("nan"),
        },
        {
            "on_window": True,
            "exclusion": None,
            "start_permitted": True,
            "horizontal_angle": True,
        },
        {
            "on_window": True,
            "exclusion": None,
            "start_permitted": True,
            "horizontal_angle": 10**400,
        },
        {
            "on_window": False,
            "exclusion": "somewhere",
            "start_permitted": False,
            "horizontal_angle": 1.0,
        },
    ],
)
def test_plain_data_that_cannot_be_read_is_refused(data: Any) -> None:
    """With a ``ValueError``, as everywhere in the core."""
    with pytest.raises(ValueError, match=r".+"):
        SunOnWindow.from_data(data)


def test_the_inputs_are_checked() -> None:
    """A tuple is no sun position."""
    with pytest.raises(TypeError, match="sun position"):
        sun_on_window((180.0, 30.0), ShadingGeometrySettings())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="measurements"):
        sun_on_window(SunPosition(180.0, 30.0), {})  # type: ignore[arg-type]
