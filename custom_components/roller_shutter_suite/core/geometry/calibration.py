"""From the covered part of a glass to a motor position, and back.

**Position convention:** as everywhere in the core, 0 is closed and 100 is
open. A covered fraction runs the other way: 0 means that the glass is free,
1 that it is fully covered. So the position falls while the covered fraction
rises.

The glass calibration of a motor states two positions: ``glass_top``, at
which the curtain reaches the upper end of the glass, and ``seat``, at which
it reaches the lower end. Between them the mapping is linear::

    position = glass_top - covered · (glass_top - seat)
    covered  = (glass_top - position) / (glass_top - seat)

Above ``glass_top`` the glass is fully free, below ``seat`` fully covered.

**Rounding happens in one place,** :func:`to_position`: half up to a whole
position. Nothing else in this package rounds.
"""

import math
from typing import Final

from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    GlassCalibration,
    Position,
)
from custom_components.roller_shutter_suite.core.model._validation import require_type

_OPEN: Final = FULLY_OPEN.value


def to_position(value: float) -> Position:
    """Round half up to a whole position. The one place that rounds."""
    return Position(max(0, min(_OPEN, math.floor(value + 0.5))))


def _require_fraction(covered: float) -> None:
    if isinstance(covered, bool) or not isinstance(covered, (int, float)):
        raise TypeError("the covered fraction must be a number")
    if not 0.0 <= covered <= 1.0:
        raise ValueError("the covered fraction must be within 0 and 1")


def ideal_position(covered: float) -> Position:
    """Return the position of a motor whose scale matches the glass exactly.

    ``100 - covered · 100``, rounded: the position "on the glass scale". It
    is the forward mapping without a calibration, computed the same way, so
    the two never differ by a rounding.
    """
    _require_fraction(covered)
    return to_position(_OPEN - covered * _OPEN)


def position_for_cover(covered: float, calibration: GlassCalibration) -> Position:
    """Return the motor position that covers this fraction of the glass (forward).

    A result that would not lie below the position of the upper glass end
    covers no glass; then the answer is "fully open", not a curtain that
    hangs in front of the frame. A fully covered glass gives the seating
    point, not 0: below it, nothing more is covered.
    """
    _require_fraction(covered)
    require_type(calibration, GlassCalibration, "the glass calibration")
    top = calibration.glass_top_position.value
    position = to_position(top - covered * calibration.span)
    return FULLY_OPEN if position.value >= top else position


def cover_at_position(position: Position, calibration: GlassCalibration) -> float:
    """Return the covered fraction of the glass at a motor position (backward).

    For the status display and the decision record. A reported position is
    an estimate on many installations, and so is this fraction.
    """
    require_type(position, Position, "the position")
    require_type(calibration, GlassCalibration, "the glass calibration")
    top = calibration.glass_top_position.value
    return max(0.0, min(1.0, (top - position.value) / calibration.span))


def end_position_for(position: Position) -> Position:
    """Return the end position for a member that cannot take an intermediate one.

    The conservative choice: **closed as soon as the computed position covers
    any glass**, open otherwise. The permitted depth is an upper limit, and of
    the two end positions only "closed" keeps it. Whether it is used is the
    decision of the shading layer.
    """
    require_type(position, Position, "the position")
    return FULLY_OPEN if position == FULLY_OPEN else FULLY_CLOSED
