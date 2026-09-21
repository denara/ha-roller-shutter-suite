"""The sun relative to one window: horizontal angle, field of view, glass plane.

Conventions (the measurements state them too, in ``core/model/geometry.py``):
angles in degrees; an azimuth runs clockwise from north; the orientation of a
window is the azimuth of its outward normal; "left" and "right" are meant as
seen from inside, looking out; the pitch is the angle between the glass and
the horizontal, 90 for vertical glass.

The frame all formulas use has its origin below the lower edge of the glass:
``x`` points to the right (seen from inside looking out), ``y`` horizontally
outwards along the normal, ``z`` up. With the horizontal angle ``g`` between
the sun and the normal and the elevation ``h``, the direction **to** the sun
is ``(cos h · sin g, cos h · cos g, sin h)``, and the outward normal of glass
with the pitch ``b`` is ``(0, sin b, cos b)``.
"""

import math
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final, Self

from custom_components.roller_shutter_suite.core.model import (
    JsonObject,
    JsonValue,
    ShadingGeometrySettings,
    SunPosition,
)
from custom_components.roller_shutter_suite.core.model._data import (
    as_bool,
    as_enum,
    as_object,
    optional,
    read,
)
from custom_components.roller_shutter_suite.core.model._validation import (
    require_optional_type,
    require_type,
)

_FULL_CIRCLE: Final = 360.0
_HALF_CIRCLE: Final = 180.0
_RIGHT_ANGLE: Final = 90.0

GRAZING: Final = 1e-9
"""The smallest incidence that counts as "the sun shines onto the glass".

The incidence is the cosine of the angle between the sun and the normal of
the glass. At and below this value the sun stands in the plane of the glass
or behind it. The value is far below anything a sun position can resolve; it
only keeps the divisions of this package away from zero.
"""


@unique
class SunExclusion(StrEnum):
    """Why the sun is not on a window. A later layer turns it into a reason code."""

    BELOW_HORIZON = "below_horizon"
    """The elevation of the sun is zero or negative."""
    BELOW_END_ELEVATION = "below_end_elevation"
    """The sun stands below the elevation at which shading ends."""
    LEFT_OF_VIEW = "left_of_view"
    """The sun stands further to the left than the field of view reaches."""
    RIGHT_OF_VIEW = "right_of_view"
    """The sun stands further to the right than the field of view reaches."""
    BEHIND_GLASS = "behind_glass"
    """The sun stands in the plane of the glass or behind it."""


def sine(degrees: float) -> float:
    """Return the sine of an angle in degrees, exact at the right angle."""
    return cosine(degrees - _RIGHT_ANGLE)


def cosine(degrees: float) -> float:
    """Return the cosine of an angle in degrees, exact at the right angles.

    The cosine of 90 degrees computed through radians is a tiny number that
    is not zero. Vertical glass and a sun exactly in the façade plane are the
    cases this package is asked about most, so they are exact.
    """
    turn = degrees % _FULL_CIRCLE
    if turn in (_RIGHT_ANGLE, _FULL_CIRCLE - _RIGHT_ANGLE):
        return 0.0
    if turn == 0.0:
        return 1.0
    if turn == _HALF_CIRCLE:
        return -1.0
    return math.cos(math.radians(turn))


def horizontal_angle(sun_azimuth: float, orientation: float) -> float:
    """Return the horizontal angle between the sun and the normal of the window.

    More than -180 and at most 180 degrees. **Positive means that the sun
    stands to the right** of the normal, seen from inside looking out: for a
    window that faces south (180), the sun in the south-west (225) is at +45.
    The subtraction wraps around north, so a window that faces 350 sees the
    sun at 10 at +20.
    """
    angle = (sun_azimuth - orientation) % _FULL_CIRCLE
    return angle - _FULL_CIRCLE if angle > _HALF_CIRCLE else angle


def incidence(elevation: float, angle: float, pitch: float) -> float:
    """Return the cosine of the angle between the sun and the normal of the glass.

    ``cos h · cos g · sin b + sin h · cos b``. Positive: the sun shines onto
    the outside of the glass. For vertical glass that is ``cos h · cos g``:
    zero in the façade plane, negative behind it. Tilted glass is also
    reached by a high sun from behind the ridge.
    """
    return cosine(elevation) * cosine(angle) * sine(pitch) + sine(elevation) * cosine(
        pitch
    )


@dataclass(frozen=True, slots=True)
class SunOnWindow:
    """Whether the sun is on a window, and if not, why.

    - ``on_window``: the sun is above the horizon and not below the end
      elevation, inside the field of view, and in front of the glass.
    - ``exclusion``: the first reason that excludes it, in the order of
      :class:`SunExclusion`; ``None`` exactly when the sun is on the window.
    - ``start_permitted``: the sun is on the window **and** at least at the
      minimum elevation for the start of shading. Whether an episode starts
      or goes on is the decision of the shading layer.
    - ``horizontal_angle``: see :func:`horizontal_angle`; ``None`` when the
      orientation of the window is not known.
    """

    on_window: bool
    exclusion: SunExclusion | None
    start_permitted: bool
    horizontal_angle: float | None

    def __post_init__(self) -> None:
        """Validate the types and that the parts agree."""
        require_type(self.on_window, bool, "the flag 'on_window'")
        require_optional_type(self.exclusion, SunExclusion, "the field 'exclusion'")
        require_type(self.start_permitted, bool, "the flag 'start_permitted'")
        if self.on_window is not (self.exclusion is None):
            raise ValueError(
                "the sun is on the window exactly when nothing excludes it "
                "(on_window, exclusion)"
            )
        if self.start_permitted and not self.on_window:
            raise ValueError(
                "shading cannot start while the sun is not on the window "
                "(start_permitted, on_window)"
            )
        if self.horizontal_angle is not None:
            angle = self.horizontal_angle
            if isinstance(angle, bool) or not isinstance(angle, (int, float)):
                raise TypeError("the field 'horizontal_angle' must be a number")
            if not -_HALF_CIRCLE < angle <= _HALF_CIRCLE:
                raise ValueError(
                    "the field 'horizontal_angle' must be more than -180 and at "
                    "most 180 degrees"
                )

    def to_data(self) -> JsonObject:
        """Return plain data."""
        return {
            "on_window": self.on_window,
            "exclusion": None if self.exclusion is None else self.exclusion.value,
            "start_permitted": self.start_permitted,
            "horizontal_angle": self.horizontal_angle,
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the value from plain data."""
        content = as_object(
            data, "on_window", "exclusion", "start_permitted", "horizontal_angle"
        )
        return cls(
            on_window=read(content, "on_window", as_bool),
            exclusion=read(content, "exclusion", optional(as_enum(SunExclusion))),
            start_permitted=read(content, "start_permitted", as_bool),
            horizontal_angle=read(content, "horizontal_angle", optional(as_float)),
        )


def as_float(value: JsonValue) -> float:
    """Read a finite number from plain data; a boolean is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected a number")  # noqa: TRY004
    if not -math.inf < value < math.inf:
        raise ValueError("expected a finite number")
    try:
        return float(value)
    except OverflowError as err:
        raise ValueError("expected a number a float can hold") from err


def _exclusion(
    sun: SunPosition, angle: float | None, settings: ShadingGeometrySettings
) -> SunExclusion | None:
    if sun.elevation <= 0:
        return SunExclusion.BELOW_HORIZON
    if sun.elevation < settings.end_elevation:
        return SunExclusion.BELOW_END_ELEVATION
    if angle is not None and angle < -settings.view_left:
        return SunExclusion.LEFT_OF_VIEW
    if angle is not None and angle > settings.view_right:
        return SunExclusion.RIGHT_OF_VIEW
    facing = 0.0 if angle is None else angle
    if incidence(sun.elevation, facing, settings.pitch) <= GRAZING:
        return SunExclusion.BEHIND_GLASS
    return None


def sun_on_window(sun: SunPosition, settings: ShadingGeometrySettings) -> SunOnWindow:
    """Return whether the sun is on the window.

    The limits of the field of view belong to it: a sun exactly at a limit is
    inside. The end elevation belongs to the sun being on the window as well;
    only below it shading ends. Without a known orientation the horizontal
    direction is not judged; the elevation limits and the glass plane still
    are, the latter with the sun straight ahead.
    """
    require_type(sun, SunPosition, "the sun position")
    require_type(settings, ShadingGeometrySettings, "the measurements of the window")
    angle = (
        horizontal_angle(sun.azimuth, settings.orientation)
        if settings.orientation_known
        else None
    )
    exclusion = _exclusion(sun, angle, settings)
    return SunOnWindow(
        on_window=exclusion is None,
        exclusion=exclusion,
        start_permitted=exclusion is None and sun.elevation >= settings.min_elevation,
        horizontal_angle=angle,
    )
