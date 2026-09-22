"""Glass calibration in both directions, and the one place that rounds."""

from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.geometry import (
    cover_at_position,
    end_position_for,
    ideal_position,
    position_for_cover,
    to_position,
)
from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    MIN_CALIBRATION_SPAN,
    NO_CALIBRATION,
    GlassCalibration,
    Position,
)

CALIBRATED = GlassCalibration(Position(12), Position(88))
CALIBRATIONS = [
    NO_CALIBRATION,
    CALIBRATED,
    GlassCalibration(Position(0), Position(MIN_CALIBRATION_SPAN)),
    GlassCalibration(Position(100 - MIN_CALIBRATION_SPAN), Position(100)),
    GlassCalibration(Position(33), Position(67)),
    GlassCalibration(Position(5), Position(100)),
    GlassCalibration(Position(0), Position(93)),
]
FRACTIONS = [step / 1000 for step in range(1001)]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (20.84, 21),
        (36.47, 36),
        (59.43, 59),
        (49.5, 50),
        (50.5, 51),
        (0.49, 0),
        (99.5, 100),
        (-3.0, 0),
        (104.2, 100),
    ],
)
def test_rounding_is_half_up_and_stays_on_the_scale(
    value: float, expected: int
) -> None:
    """Half up, not half to even; never outside 0 to 100."""
    assert to_position(value) == Position(expected)


def test_a_position_falls_while_the_covered_fraction_rises() -> None:
    """0 is closed, 100 is open: nothing covered is open, everything covered closed."""
    assert ideal_position(0.0) == FULLY_OPEN
    assert ideal_position(1.0) == FULLY_CLOSED
    assert ideal_position(0.4) == Position(60)
    assert ideal_position(0.25) == Position(75)


def test_the_defaults_change_nothing() -> None:
    """Without a calibration, the motor position is the ideal position."""
    for covered in FRACTIONS:
        assert position_for_cover(covered, NO_CALIBRATION) == ideal_position(covered)


def test_no_calibration_maps_positions_and_fractions_one_to_one() -> None:
    """Backward as well."""
    for value in range(101):
        assert cover_at_position(Position(value), NO_CALIBRATION) == pytest.approx(
            (100 - value) / 100
        )


def test_between_the_two_points_the_mapping_is_linear() -> None:
    """Seating point 12, upper glass end 88: half covered is the middle, 50."""
    assert position_for_cover(0.5, CALIBRATED) == Position(50)
    assert position_for_cover(0.25, CALIBRATED) == Position(69)
    assert position_for_cover(1.0, CALIBRATED) == Position(12)
    assert cover_at_position(Position(50), CALIBRATED) == pytest.approx(0.5)
    assert cover_at_position(Position(69), CALIBRATED) == pytest.approx(0.25)


def test_outside_the_two_points_the_glass_is_fully_free_or_fully_covered() -> None:
    """Backward: above the glass top nothing is covered, below the seat everything."""
    for value in (88, 90, 100):
        assert cover_at_position(Position(value), CALIBRATED) == 0.0
    for value in (12, 5, 0):
        assert cover_at_position(Position(value), CALIBRATED) == 1.0


def test_a_target_that_covers_no_glass_is_fully_open() -> None:
    """Not a curtain that hangs in front of the frame at the glass-top position."""
    assert position_for_cover(0.0, CALIBRATED) == FULLY_OPEN
    assert position_for_cover(0.004, CALIBRATED) == FULLY_OPEN
    assert position_for_cover(0.01, CALIBRATED) == Position(87)


@pytest.mark.parametrize("calibration", CALIBRATIONS)
def test_forward_and_backward_are_inverse_within_rounding(
    calibration: GlassCalibration,
) -> None:
    """Forward, backward, forward again gives the same position: it is stable.

    And the fraction that comes back differs from the one that went in by no
    more than half a position of the calibrated range, except where the
    target was "fully open".
    """
    half_step = 0.5 / calibration.span
    for covered in FRACTIONS:
        position = position_for_cover(covered, calibration)
        back = cover_at_position(position, calibration)

        assert position_for_cover(back, calibration) == position
        if position != FULLY_OPEN:
            assert abs(back - covered) <= half_step + 1e-12
        else:
            assert back == 0.0


@pytest.mark.parametrize("calibration", CALIBRATIONS)
def test_backward_then_forward_is_stable_for_every_reported_position(
    calibration: GlassCalibration,
) -> None:
    """Inside the calibrated range a position maps to itself."""
    seat = calibration.seat_position.value
    top = calibration.glass_top_position.value
    for value in range(101):
        again = position_for_cover(
            cover_at_position(Position(value), calibration), calibration
        )
        if seat <= value < top:
            assert again == Position(value)
        elif value < seat:
            assert again == calibration.seat_position
        else:
            assert again == FULLY_OPEN


@pytest.mark.parametrize("calibration", CALIBRATIONS)
def test_more_cover_never_means_a_higher_position(
    calibration: GlassCalibration,
) -> None:
    """Monotonic, and always within the calibrated range or fully open."""
    positions = [position_for_cover(covered, calibration) for covered in FRACTIONS]

    assert positions == sorted(positions, reverse=True)
    assert positions[0] == FULLY_OPEN
    assert positions[-1] == calibration.seat_position


def test_the_conservative_end_position_closes_as_soon_as_any_glass_is_covered() -> None:
    """For a member that cannot take an intermediate position."""
    assert end_position_for(FULLY_OPEN) == FULLY_OPEN
    assert end_position_for(Position(99)) == FULLY_CLOSED
    assert end_position_for(Position(50)) == FULLY_CLOSED
    assert end_position_for(FULLY_CLOSED) == FULLY_CLOSED


@pytest.mark.parametrize("covered", [-0.01, 1.01, float("nan"), float("inf")])
def test_a_fraction_outside_zero_to_one_is_refused(covered: float) -> None:
    """In both functions that take one."""
    with pytest.raises(ValueError, match="covered fraction"):
        ideal_position(covered)
    with pytest.raises(ValueError, match="covered fraction"):
        position_for_cover(covered, NO_CALIBRATION)


@pytest.mark.parametrize("covered", [True, "0.5", None])
def test_a_fraction_that_is_no_number_is_refused(covered: Any) -> None:
    """A boolean is not a number."""
    with pytest.raises(TypeError, match="covered fraction"):
        ideal_position(covered)


def test_the_other_inputs_are_checked() -> None:
    """Positions and calibrations are the types of the model."""
    with pytest.raises(TypeError, match="calibration"):
        position_for_cover(0.5, (12, 88))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="calibration"):
        cover_at_position(Position(50), None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="position"):
        cover_at_position(50, NO_CALIBRATION)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="position"):
        end_position_for(50)  # type: ignore[arg-type]
