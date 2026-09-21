"""One element, one curtain edge: the examples on paper, the grid, the result type."""

import itertools
import json
import math
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.geometry import (
    MemberShading,
    ShadedElement,
    ShadingGeometry,
    SunExclusion,
    SunOnWindow,
    compute_shading,
    covered_fraction,
    curtain_edge,
    free_glass_length,
    members_for_edge,
)
from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    GlassCalibration,
    MemberGlass,
    Position,
    ShadingGeometrySettings,
    SunPosition,
)

SOUTH = 180.0
MAX_POSITION = 100
ANGLE_AT_THE_CAP = 60


def _measured(**changes: Any) -> ShadingGeometrySettings:
    arguments: dict[str, Any] = {
        "use_measurements": True,
        "orientation_known": True,
        "orientation": SOUTH,
    }
    return ShadingGeometrySettings(**(arguments | changes))


def _positions(result: ShadingGeometry) -> list[int]:
    return [member.position.value for member in result.members]


# --- Decision 9, first example: two members of different glass height -------------------

# Same sill height of 0.9 m, glass heights 1.4 m and 0.8 m, permitted depth
# 1.0 m, vertical glass, sun straight ahead. The element is as high as the
# large member; the top of the small one lies 0.6 m below the top of the
# element.
UNEQUAL = ShadedElement(
    _measured(element_bottom=0.9, element_height=1.4, depth=1.0),
    (
        MemberGlass("cover.example_large", 1.4),
        MemberGlass("cover.example_small", 0.8, top_offset=0.6),
    ),
)


@pytest.mark.parametrize(
    ("elevation", "ray_height", "large", "small"),
    [(50.0, 1.19, 21, 36), (60.0, 1.73, 59, 100)],
)
def test_decision_9_unequal_members_get_their_own_positions(
    elevation: float, ray_height: float, large: int, small: int
) -> None:
    """The numbers of the table in the architecture document."""
    result = compute_shading(SunPosition(SOUTH, elevation), UNEQUAL)

    assert result.sun.on_window
    assert result.computed
    assert result.ray_height is not None
    assert round(result.ray_height, 2) == ray_height
    assert _positions(result) == [large, small]
    assert [member.ideal_position.value for member in result.members] == [large, small]


@pytest.mark.parametrize(
    ("elevation", "ray_height", "covered", "position"),
    [
        (35.0, 0.70, 1.40, 0),
        (50.0, 1.19, 1.11, 21),
        (60.0, 1.73, 0.57, 59),
        (70.0, 2.75, 0.0, 100),
    ],
)
def test_the_window_example_of_the_user_documentation(
    elevation: float, ray_height: float, covered: float, position: int
) -> None:
    """The table "a normal window" of ``docs/features/shading-geometry.md``."""
    result = compute_shading(SunPosition(SOUTH, elevation), UNEQUAL)

    assert result.ray_height is not None
    assert result.curtain_edge is not None
    assert round(result.ray_height, 2) == ray_height
    assert round(result.curtain_edge, 2) == covered
    assert result.members[0].position.value == position


# --- Decision 9, second example: two rows, one curtain edge ------------------------------

# Upper row with offset 0 and glass height 1.0 m, lower row with offset 1.1 m
# (the frame in between counts) and glass height 0.6 m.
ROWS = (
    MemberGlass("cover.example_upper", 1.0),
    MemberGlass("cover.example_lower", 0.6, top_offset=1.1),
)


@pytest.mark.parametrize(
    ("edge", "upper", "upper_covered", "lower", "lower_covered"),
    [
        (0.4, 60, 0.4, 100, 0.0),
        (1.05, 0, 1.0, 100, 0.0),
        (1.4, 0, 1.0, 50, 0.5),
    ],
)
def test_decision_9_two_rows_share_one_curtain_edge(
    edge: float, upper: int, upper_covered: float, lower: int, lower_covered: float
) -> None:
    """The three rows of the table: in the upper row, in the frame, in the lower row."""
    first, second = members_for_edge(edge, ROWS)

    assert (first.position.value, second.position.value) == (upper, lower)
    assert first.covered_fraction == pytest.approx(upper_covered)
    assert second.covered_fraction == pytest.approx(lower_covered)


@pytest.mark.parametrize(
    ("edge", "upper", "lower"), [(0.4, 60, 100), (1.05, 0, 100), (1.4, 0, 50)]
)
def test_decision_9_two_rows_from_the_sun_position(
    edge: float, upper: int, lower: int
) -> None:
    """The same rows through the whole module, as a vertical element.

    Lower edge 0.5 m above the floor, element 1.7 m high, permitted depth
    1.0 m: the curtain edge ``e`` belongs to the ray height 2.2 m - ``e``,
    and with the sun straight ahead to the elevation whose tangent that is.
    """
    element = ShadedElement(
        _measured(element_bottom=0.5, element_height=1.7, depth=1.0), ROWS
    )
    elevation = math.degrees(math.atan(2.2 - edge))

    result = compute_shading(SunPosition(SOUTH, elevation), element)

    assert result.curtain_edge == pytest.approx(edge)
    assert result.ray_height == pytest.approx(2.2 - edge)
    assert _positions(result) == [upper, lower]


# --- The roof element of the documentation ------------------------------------------------

# Pitch 40 degrees, lower edge of the glass 1.0 m above the floor, the two
# rows from above (element 1.7 m along the glass), permitted depth 1.5 m.
ROOF = ShadedElement(
    _measured(
        element_bottom=1.0,
        element_height=1.7,
        depth=1.5,
        pitch=40.0,
        view_left=120.0,
        view_right=120.0,
    ),
    ROWS,
)


@pytest.mark.parametrize(
    ("sun", "ray_height", "edge", "positions"),
    [
        (SunPosition(180.0, 30.0), 0.92, 1.70, [0, 0]),
        (SunPosition(180.0, 45.0), 1.23, 1.35, [0, 59]),
        (SunPosition(180.0, 60.0), 1.52, 0.89, [11, 100]),
        (SunPosition(180.0, 75.0), 1.84, 0.39, [61, 100]),
        (SunPosition(230.0, 45.0), 1.47, 0.97, [3, 100]),
    ],
)
def test_the_roof_example_of_the_documentation(
    sun: SunPosition, ray_height: float, edge: float, positions: list[int]
) -> None:
    """The table of ``docs/features/shading-geometry.md``, row by row.

    Ray height and curtain edge in metres, rounded to centimetres as in the
    table; the positions of the upper and of the lower row.
    """
    result = compute_shading(sun, ROOF)

    assert result.ray_height is not None
    assert result.curtain_edge is not None
    assert round(result.ray_height, 2) == ray_height
    assert round(result.curtain_edge, 2) == edge
    assert _positions(result) == positions


def test_the_roof_formula_on_paper_for_one_row_of_the_table() -> None:
    """45 degrees straight ahead, computed here step by step.

    A point of the glass ``t`` above its lower edge lies ``1.0 + t · sin 40``
    high and ``t · cos 40`` inside the room; its ray reaches the floor
    ``height / tan 45`` further inside. That sum is 1.5 m at ``t_free``.
    """
    sin_b, cos_b = math.sin(math.radians(40.0)), math.cos(math.radians(40.0))
    t_free = (1.5 - 1.0) / (cos_b + sin_b)  # tan 45 is 1

    result = compute_shading(SunPosition(SOUTH, 45.0), ROOF)

    assert t_free * cos_b + (1.0 + t_free * sin_b) == pytest.approx(1.5)
    assert result.curtain_edge == pytest.approx(1.7 - t_free)
    assert result.ray_height == pytest.approx(1.0 + t_free * sin_b)


# --- A pitch of 90 degrees is the vertical case --------------------------------------------


def _vertical_on_paper(
    settings: ShadingGeometrySettings, angle: float, elevation: float
) -> tuple[float, float]:
    """Return ray height and curtain edge by the formula for vertical glass."""
    cos_g = max(math.cos(math.radians(angle)), 1.0 / settings.amplification_cap)
    ray_height = settings.depth * math.tan(math.radians(elevation)) / cos_g
    top = settings.element_bottom + settings.element_height
    return ray_height, max(0.0, min(settings.element_height, top - ray_height))


def test_a_pitch_of_90_degrees_gives_exactly_the_vertical_results() -> None:
    """``ray height = depth · tan(elevation) / cos(angle)``, edge = top - ray height."""
    settings = _measured(element_bottom=0.9, element_height=1.4, depth=1.0, pitch=90.0)
    element = ShadedElement(settings, UNEQUAL.members)
    for angle, elevation in itertools.product(
        (-80.0, -60.0, -25.0, 0.0, 10.0, 45.0, 60.0, 75.0, 89.0),
        (1.0, 10.0, 35.0, 50.0, 60.0, 80.0, 89.0),
    ):
        ray_height, edge = _vertical_on_paper(settings, angle, elevation)

        result = compute_shading(SunPosition(SOUTH + angle, elevation), element)

        assert result.ray_height == pytest.approx(ray_height, rel=1e-12)
        assert result.curtain_edge == pytest.approx(edge, rel=1e-12, abs=1e-12)
        assert _positions(result) == _positions(
            ShadingGeometry(
                result.sun,
                True,
                ray_height,
                edge,
                members_for_edge(edge, element.members),
            )
        )


def test_the_default_pitch_is_vertical() -> None:
    """A window that states no pitch is computed as vertical glass."""
    stated = ShadedElement(_measured(pitch=90.0), (MemberGlass("cover.example", 1.2),))
    default = ShadedElement(_measured(), (MemberGlass("cover.example", 1.2),))
    sun = SunPosition(200.0, 33.0)

    assert compute_shading(sun, stated) == compute_shading(sun, default)


# --- Oblique sun: the shutter stays higher, up to the cap ------------------------------------


def test_the_more_oblique_the_sun_the_higher_the_shutter_stays_up_to_the_cap() -> None:
    """Monotonic in the horizontal angle, on both sides; constant beyond the cap.

    The default cap of 2 is reached at 60 degrees. At and beyond the façade
    plane the sun is not on the window.
    """
    element = ShadedElement(
        _measured(element_bottom=0.9, element_height=1.4, depth=1.2),
        (MemberGlass("cover.example_window", 1.4),),
    )

    def at(angle: float) -> ShadingGeometry:
        return compute_shading(SunPosition(SOUTH + angle, 40.0), element)

    for side in (1.0, -1.0):
        results = [at(side * angle) for angle in range(90)]
        heights = [result.ray_height for result in results]
        positions = [result.members[0].position for result in results]

        assert all(height is not None for height in heights)
        assert heights == sorted(heights)  # type: ignore[type-var]
        assert positions == sorted(positions)
        rising = heights[: ANGLE_AT_THE_CAP + 1]
        assert len(set(rising)) == len(rising)
        capped = heights[ANGLE_AT_THE_CAP:]
        assert capped == [pytest.approx(capped[0])] * len(capped)
        assert heights[60] == pytest.approx(2 * heights[0])  # type: ignore[operator]
        assert positions[0] < positions[60]
        assert at(side * 90.0).sun.exclusion is SunExclusion.BEHIND_GLASS
        assert not at(side * 120.0).sun.on_window


def test_the_cap_is_a_parameter() -> None:
    """A cap of 1 switches the amplification off; a larger one lets it go on."""
    members = (MemberGlass("cover.example_window", 1.4),)
    sun = SunPosition(SOUTH + 70.0, 40.0)

    def ray_height(cap: float) -> float:
        element = ShadedElement(
            _measured(element_height=1.4, amplification_cap=cap), members
        )
        height = compute_shading(sun, element).ray_height
        assert height is not None
        return height

    straight = 0.5 * math.tan(math.radians(40.0))
    assert ray_height(1.0) == pytest.approx(straight)
    assert ray_height(2.0) == pytest.approx(2.0 * straight)
    assert ray_height(10.0) == pytest.approx(straight / math.cos(math.radians(70.0)))


def test_the_higher_the_sun_the_higher_the_shutter_stays() -> None:
    """Monotonic in the elevation, for vertical and for tilted glass."""
    for element in (UNEQUAL, ROOF):
        results = [
            compute_shading(SunPosition(SOUTH, float(elevation)), element)
            for elevation in range(1, 90)
        ]
        for index in range(len(element.members)):
            positions = [result.members[index].position for result in results]
            assert positions == sorted(positions)


def test_a_depth_of_zero_lets_no_sun_in() -> None:
    """Everything is covered whenever the sun is on the window."""
    element = ShadedElement(_measured(depth=0.0), (MemberGlass("cover.example", 1.2),))

    result = compute_shading(SunPosition(SOUTH, 45.0), element)

    assert result.curtain_edge == pytest.approx(1.2)
    assert _positions(result) == [0]


def test_without_a_known_orientation_the_sun_counts_as_straight_ahead() -> None:
    """The deepest the sun can shine: never less shade than the real angle needs."""
    known = ShadedElement(_measured(element_height=1.4), UNEQUAL.members[:1])
    unknown = ShadedElement(
        _measured(element_height=1.4, orientation_known=False), UNEQUAL.members[:1]
    )

    straight = compute_shading(SunPosition(SOUTH, 40.0), known)
    oblique = compute_shading(SunPosition(SOUTH + 50.0, 40.0), known)
    anywhere = compute_shading(SunPosition(20.0, 40.0), unknown)

    assert anywhere.sun.horizontal_angle is None
    assert anywhere.ray_height == straight.ray_height
    assert anywhere.members == straight.members
    assert anywhere.members[0].position <= oblique.members[0].position


# --- The pieces -------------------------------------------------------------------------------


def test_the_curtain_edge_is_clamped_to_the_element() -> None:
    """Negative free length: everything covered. More than the element: nothing."""
    assert curtain_edge(-0.3, 1.7) == pytest.approx(1.7)
    assert curtain_edge(0.0, 1.7) == pytest.approx(1.7)
    assert curtain_edge(0.5, 1.7) == pytest.approx(1.2)
    assert curtain_edge(1.7, 1.7) == 0.0
    assert curtain_edge(25.0, 1.7) == 0.0


def test_a_member_covers_the_part_of_the_edge_inside_its_own_range() -> None:
    """``clamp(e - offset, 0, glass height) / glass height``."""
    lower = ROWS[1]

    assert covered_fraction(0.0, lower) == 0.0
    assert covered_fraction(1.1, lower) == 0.0
    assert covered_fraction(1.25, lower) == pytest.approx(0.25)
    assert covered_fraction(1.7, lower) == pytest.approx(1.0)
    assert covered_fraction(5.0, lower) == 1.0


def test_the_free_length_is_not_clamped() -> None:
    """It says how far the limit lies outside the element, in both directions."""
    settings = _measured(element_bottom=0.9, element_height=1.4, depth=1.0)

    assert free_glass_length(10.0, 0.0, settings) < 0
    assert free_glass_length(80.0, 0.0, settings) > settings.element_height
    assert free_glass_length(50.0, None, settings) == free_glass_length(
        50.0, 0.0, settings
    )


def test_equal_members_get_equal_positions() -> None:
    """Whatever the sun does."""
    glass: dict[str, Any] = {"glass_height": 1.2, "top_offset": 0.0}
    element = ShadedElement(
        _measured(),
        (
            MemberGlass("cover.example_left", **glass),
            MemberGlass("cover.example_middle", **glass),
            MemberGlass("cover.example_right", **glass),
        ),
    )
    for azimuth, elevation in itertools.product(range(100, 261, 20), range(5, 90, 10)):
        result = compute_shading(SunPosition(float(azimuth), float(elevation)), element)

        assert len(set(_positions(result))) == 1
        assert len({member.covered_fraction for member in result.members}) == 1


def test_each_member_is_mapped_through_its_own_calibration() -> None:
    """Same glass, different motors: same ideal position, different targets."""
    element = ShadedElement(
        _measured(element_bottom=0.9, element_height=1.4, depth=1.0),
        (
            MemberGlass("cover.example_left", 1.4),
            MemberGlass(
                "cover.example_right",
                1.4,
                calibration=GlassCalibration(Position(10), Position(90)),
            ),
        ),
    )

    left, right = compute_shading(SunPosition(SOUTH, 60.0), element).members

    assert left.covered_fraction == right.covered_fraction
    assert (left.ideal_position, right.ideal_position) == (Position(59), Position(59))
    assert (left.position, right.position) == (Position(59), Position(58))


def test_the_conservative_end_position_is_offered_next_to_the_ideal_one() -> None:
    """Closed as soon as the member's target covers any glass; else open."""
    at_60 = compute_shading(SunPosition(SOUTH, 60.0), UNEQUAL)

    large, small = at_60.members
    assert (large.position, large.end_position) == (Position(59), FULLY_CLOSED)
    assert (small.position, small.end_position) == (FULLY_OPEN, FULLY_OPEN)


# --- Simple mode and "not on the window" -----------------------------------------------------


def test_the_simple_mode_has_the_same_interface_and_a_fixed_position() -> None:
    """Sun on the window: the fixed position for every member, nothing computed."""
    settings = ShadingGeometrySettings(
        orientation_known=True, orientation=SOUTH, fixed_position=Position(25)
    )
    element = ShadedElement(
        settings, (MemberGlass("cover.example_a", 1.2), MemberGlass("cover.b", 1.2))
    )

    shaded = compute_shading(SunPosition(SOUTH, 30.0), element)
    away = compute_shading(SunPosition(0.0, 30.0), element)

    assert shaded.sun.on_window
    assert not shaded.computed
    assert shaded.ray_height is None
    assert shaded.curtain_edge is None
    assert _positions(shaded) == [25, 25]
    assert {member.covered_fraction for member in shaded.members} == {None}
    assert {member.ideal_position for member in shaded.members} == {Position(25)}
    assert {member.end_position for member in shaded.members} == {FULLY_CLOSED}
    assert away.sun.exclusion is SunExclusion.RIGHT_OF_VIEW
    assert _positions(away) == [100, 100]


def test_the_simple_mode_without_an_orientation_follows_the_elevation_only() -> None:
    """The defaults of a new window: the fixed position while the sun is up."""
    element = ShadedElement(
        ShadingGeometrySettings(), (MemberGlass("cover.example_window", 1.2),)
    )

    assert _positions(compute_shading(SunPosition(10.0, 25.0), element)) == [30]
    assert _positions(compute_shading(SunPosition(10.0, -5.0), element)) == [100]


def test_while_the_sun_is_not_on_the_window_the_geometry_asks_for_nothing() -> None:
    """Every member open, no ray height, and the reason is part of the result."""
    result = compute_shading(SunPosition(SOUTH, -2.0), UNEQUAL)

    assert result.sun.exclusion is SunExclusion.BELOW_HORIZON
    assert result.computed
    assert result.ray_height is None
    assert result.curtain_edge is None
    assert _positions(result) == [100, 100]
    assert {member.covered_fraction for member in result.members} == {0.0}
    assert {member.end_position for member in result.members} == {FULLY_OPEN}


# --- The grid: any sun position, any valid measurements --------------------------------------

AZIMUTHS = [float(value) for value in range(0, 360, 15)] + [359.999, 0.001, 90.0]
ELEVATIONS = [
    -90.0,
    -45.0,
    -0.001,
    0.0,
    5e-324,
    1e-300,
    1e-9,
    0.001,
    1.0,
    15.0,
    39.999,
    40.0,
    40.001,
    45.0,
    60.0,
    89.0,
    89.999999,
    90.0,
]
GRID_MEMBERS = (
    MemberGlass("cover.example_upper", 0.05),
    MemberGlass(
        "cover.example_lower",
        0.04,
        top_offset=0.06,
        calibration=GlassCalibration(Position(45), Position(55)),
    ),
)
GRID_SETTINGS = [
    _measured(**({"element_height": 0.1} | changes))
    for changes in (
        {},
        {"pitch": 0.0},
        {"pitch": 40.0, "view_left": 180.0, "view_right": 180.0},
        {"pitch": 89.999999, "view_left": 180.0, "view_right": 180.0},
        {"pitch": 1e-9, "orientation": 0.0},
        {"depth": 0.0, "element_bottom": 0.0},
        {"depth": 100.0, "element_bottom": 100.0, "amplification_cap": 10.0},
        {"depth": 100.0, "element_bottom": 0.0, "amplification_cap": 1.0},
        {"depth": 1e-12, "element_bottom": 1e-12, "pitch": 12.5},
        {"orientation": 359.999, "view_left": 1e-9, "view_right": 180.0},
        {"orientation_known": False, "pitch": 40.0},
        {"min_elevation": 90.0, "end_elevation": 90.0},
        {"use_measurements": False, "fixed_position": Position(0)},
        {"element_height": 100.0, "pitch": 40.0, "depth": 3.0},
    )
]


@pytest.mark.parametrize("settings", GRID_SETTINGS)
def test_no_sun_position_breaks_the_geometry(settings: ShadingGeometrySettings) -> None:
    """No exception, no division by zero, every position within 0 and 100.

    Elevation 0, 90 and negative are part of the grid, and so are the
    smallest numbers a float can hold, a sun exactly in the plane of tilted
    glass, glass that lies flat, and measurements at the ends of their
    ranges.
    """
    element = ShadedElement(settings, GRID_MEMBERS)
    for azimuth, elevation in itertools.product(AZIMUTHS, ELEVATIONS):
        result = compute_shading(SunPosition(azimuth, elevation), element)

        for member in result.members:
            for position in (
                member.ideal_position,
                member.position,
                member.end_position,
            ):
                assert 0 <= position.value <= MAX_POSITION
            assert member.end_position in {FULLY_OPEN, FULLY_CLOSED}
        if result.ray_height is not None:
            assert math.isfinite(result.ray_height)
            assert result.curtain_edge is not None
            assert 0.0 <= result.curtain_edge <= settings.element_height
        if elevation <= 0:
            assert not result.sun.on_window
        assert ShadingGeometry.from_data(result.to_data()) == result


# --- The element validates itself ---------------------------------------------------------------


def test_the_glass_of_every_member_lies_inside_the_element() -> None:
    """The message names the fields and the member."""
    with pytest.raises(ValueError, match=r"top_offset.*cover\.example_lower") as error:
        ShadedElement(
            _measured(element_height=1.6),
            (
                MemberGlass("cover.example_upper", 1.0),
                MemberGlass("cover.example_lower", 0.6, top_offset=1.1),
            ),
        )

    assert "glass_height" in str(error.value)
    assert "element_height" in str(error.value)
    assert ShadedElement(_measured(element_height=1.7), ROWS)


@pytest.mark.parametrize(
    ("settings", "members", "error"),
    [
        (ShadingGeometrySettings(), (), ValueError),
        (ShadingGeometrySettings(), ("cover.example",), TypeError),
        ({}, (MemberGlass("cover.example", 1.2),), TypeError),
        (
            ShadingGeometrySettings(),
            (MemberGlass("cover.example", 1.2), MemberGlass("cover.example", 1.0)),
            ValueError,
        ),
    ],
)
def test_an_element_that_cannot_work_is_refused(
    settings: Any, members: Any, error: type[Exception]
) -> None:
    """No member, a member twice, the wrong types."""
    with pytest.raises(error):
        ShadedElement(settings, members)


def test_the_inputs_of_the_entry_point_are_checked() -> None:
    """A sun position and an element, nothing else."""
    with pytest.raises(TypeError, match="sun position"):
        compute_shading((SOUTH, 30.0), UNEQUAL)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="element"):
        compute_shading(SunPosition(SOUTH, 30.0), UNEQUAL.settings)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="curtain edge"):
        members_for_edge(-0.1, ROWS)
    with pytest.raises(ValueError, match="curtain edge"):
        members_for_edge(float("nan"), ROWS)
    with pytest.raises(TypeError, match="member"):
        members_for_edge(0.5, ("cover.example",))  # type: ignore[arg-type]


# --- The result type -------------------------------------------------------------------------------


def test_the_result_survives_plain_data_and_finds_its_members() -> None:
    """The decision record will carry it; JSON has to be enough."""
    for sun in (SunPosition(SOUTH, 50.0), SunPosition(0.0, 50.0)):
        result = compute_shading(sun, UNEQUAL)
        data = json.loads(json.dumps(result.to_data()))

        assert ShadingGeometry.from_data(data) == result
    assert result.member("cover.example_small").position == FULLY_OPEN
    with pytest.raises(KeyError):
        result.member("cover.example_unknown")


_SUN = SunOnWindow(True, None, True, 0.0)
_MEMBER = MemberShading("cover.example", 0.5, Position(50), Position(50), FULLY_CLOSED)


@pytest.mark.parametrize(
    "build",
    [
        lambda: ShadingGeometry(_SUN, True, 1.2, None, (_MEMBER,)),
        lambda: ShadingGeometry(_SUN, True, None, 0.4, (_MEMBER,)),
        lambda: ShadingGeometry(_SUN, True, float("inf"), 0.4, (_MEMBER,)),
        lambda: ShadingGeometry(_SUN, True, 1.2, -0.1, (_MEMBER,)),
        lambda: ShadingGeometry(_SUN, True, 1.2, 0.4, ()),
        lambda: ShadingGeometry(_SUN, True, 1.2, 0.4, (_MEMBER, _MEMBER)),
        lambda: ShadingGeometry(_SUN, True, 1.2, 0.4, ("cover.example",)),  # type: ignore[arg-type]
        lambda: ShadingGeometry(_SUN, "yes", 1.2, 0.4, (_MEMBER,)),  # type: ignore[arg-type]
        lambda: ShadingGeometry(None, True, 1.2, 0.4, (_MEMBER,)),  # type: ignore[arg-type]
        lambda: MemberShading("", 0.5, Position(50), Position(50), FULLY_CLOSED),
        lambda: MemberShading("cover.a", 1.5, Position(50), Position(50), FULLY_OPEN),
        lambda: MemberShading(
            "cover.a", float("nan"), FULLY_OPEN, FULLY_OPEN, FULLY_OPEN
        ),
        lambda: MemberShading("cover.a", 0.5, 50, Position(50), FULLY_OPEN),  # type: ignore[arg-type]
    ],
)
def test_a_result_that_cannot_be_is_refused(build: Any) -> None:
    """An object that exists is valid."""
    with pytest.raises((TypeError, ValueError)):
        build()


@pytest.mark.parametrize(
    "change",
    [
        {"members": []},
        {"members": [{"member_id": "cover.example"}]},
        {"ray_height": "1.2"},
        {"computed": 1},
        {"sun": None},
        {"unheard_of": 1},
    ],
)
def test_plain_data_of_a_result_that_cannot_be_read_is_refused(
    change: dict[str, Any],
) -> None:
    """With a ``ValueError`` that leads to the key."""
    data = compute_shading(SunPosition(SOUTH, 50.0), UNEQUAL).to_data()

    with pytest.raises(ValueError, match=r".+"):
        ShadingGeometry.from_data(data | change)
