"""Sun geometry and glass calibration: plain geometry, nothing else.

For a sun position and a window, this package answers: is the sun on the
window at all, and to which position does each member have to move so that
the sun enters the room no further than permitted? It knows nothing about
layers, episodes, temperatures or Home Assistant, reads no clock and asks no
port. Every function is pure, every type is frozen.

:func:`compute_shading` is the one entry point for the shading layer. The
measurements it works with are values of the core model
(``ShadingGeometrySettings``, ``MemberGlass``, ``GlassCalibration``); the
conventions are stated there and in ``docs/dev/geometry.md``.
"""

from .calibration import (
    cover_at_position,
    end_position_for,
    ideal_position,
    position_for_cover,
    to_position,
)
from .element import (
    MemberShading,
    ShadedElement,
    ShadingGeometry,
    compute_shading,
    covered_fraction,
    curtain_edge,
    free_glass_length,
    members_for_edge,
)
from .sun import (
    GRAZING,
    SunExclusion,
    SunOnWindow,
    horizontal_angle,
    incidence,
    sun_on_window,
)

__all__ = [
    "GRAZING",
    "MemberShading",
    "ShadedElement",
    "ShadingGeometry",
    "SunExclusion",
    "SunOnWindow",
    "compute_shading",
    "cover_at_position",
    "covered_fraction",
    "curtain_edge",
    "end_position_for",
    "free_glass_length",
    "horizontal_angle",
    "ideal_position",
    "incidence",
    "members_for_edge",
    "position_for_cover",
    "sun_on_window",
    "to_position",
]
