"""One element, one curtain edge: from the sun position to a position per member.

The glass of a window is treated as one **element**: a strip of glass of the
height ``L`` (``element_height``, along the glass) whose lower edge lies
``B`` (``element_bottom``) above the floor and whose top leans into the room
by the pitch ``b``. A point of the glass at the length ``t`` above the lower
edge lies ``B + t · sin b`` above the floor and ``t · cos b`` inside the room.
A ray of the sun through that point reaches the floor at the depth ::

    d(t) = t · cos b + (B + t · sin b) · cos g / tan h

with the elevation ``h`` and the horizontal angle ``g`` of the sun. The depth
is measured on the floor, perpendicular to the façade, from the point below
the lower edge of the glass. ``d`` grows with ``t``, so the glass may stay
free from its lower edge up to the length at which ``d`` reaches the
permitted depth ``D``::

    t_free = (D · sin h - B · c) / (c · sin b + sin h · cos b),   c = cos h · cos g

For vertical glass (``b = 90``) this is ``D · tan h / cos g - B``: the **ray
height** ``D · tan h / cos g`` minus the height of the lower edge. The factor
``1 / cos g`` is the amplification for oblique sun; it is capped, which the
formula does by never letting ``cos g`` fall below ``1 / cap``. The
denominator is the incidence of the sun on the glass (with the capped
cosine), which is positive whenever the sun is on the window, so nothing here
divides by zero.

The curtain edge is the covered length from the top of the element,
``e = clamp(L - t_free, 0, L)``, and each member covers the part of it that
falls into its own range: ``clamp(e - offset, 0, glass height)``.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Self

from custom_components.roller_shutter_suite.core.model import (
    FULLY_OPEN,
    JsonObject,
    JsonValue,
    MemberGlass,
    Position,
    ShadingGeometrySettings,
    SunPosition,
)
from custom_components.roller_shutter_suite.core.model._data import (
    as_bool,
    as_int,
    as_object,
    as_str,
    optional,
    read,
    tuple_of,
)
from custom_components.roller_shutter_suite.core.model._validation import (
    require_finite,
    require_identifier,
    require_type,
    require_unique,
)

from .calibration import end_position_for, ideal_position, position_for_cover
from .sun import SunOnWindow, as_float, cosine, sine, sun_on_window


@dataclass(frozen=True, slots=True)
class ShadedElement:
    """What the geometry computes for: the measurements of a window and its members.

    Every member of the window appears once, with the measurements that
    apply to it (its own, or those inherited from the window). The glass of
    every member lies inside the element.
    """

    settings: ShadingGeometrySettings
    members: tuple[MemberGlass, ...]

    def __post_init__(self) -> None:
        """Validate the parts and that every member fits into the element."""
        require_type(
            self.settings, ShadingGeometrySettings, "the measurements of the window"
        )
        object.__setattr__(self, "members", tuple(self.members))
        if not self.members:
            raise ValueError("an element has at least one member")
        for member in self.members:
            require_type(member, MemberGlass, "a member of an element")
        require_unique(
            (member.member_id for member in self.members), "the members of an element"
        )
        for member in self.members:
            if not member.fits_into(self.settings.element_height):
                raise ValueError(
                    f"the fields 'top_offset' and 'glass_height' of the member "
                    f"{member.member_id!r} reach below the element: together they "
                    "must not exceed the field 'element_height' of the window"
                )


STRAIGHT_AHEAD: Final = 0.0
"""The horizontal angle of a sun that stands exactly in front of the window.

For callers that ask for the frontal case by name: worked examples and
tables. It is never what happens when the orientation is missing.
"""


def _capped_cosine(angle: float, cap: float) -> float:
    """Return ``cos g``, never below ``1 / cap``."""
    return max(cosine(angle), 1.0 / cap)


def free_glass_length(
    elevation: float, angle: float, settings: ShadingGeometrySettings
) -> float:
    """Return ``t_free``: how far up from its lower edge the glass may stay free.

    Along the glass, not clamped to the element: negative when even the lower
    edge lets the sun in too far, larger than the element when nothing has to
    be covered. Only defined while the sun is on the window.
    """
    across = cosine(elevation) * _capped_cosine(angle, settings.amplification_cap)
    up = sine(elevation)
    denominator = across * sine(settings.pitch) + up * cosine(settings.pitch)
    return (settings.depth * up - settings.element_bottom * across) / denominator


def curtain_edge(free_length: float, element_height: float) -> float:
    """Return ``e``: the covered length from the top of the element, clamped to it."""
    return max(0.0, min(element_height, element_height - free_length))


def covered_fraction(edge: float, member: MemberGlass) -> float:
    """Return the part of a member's glass that the curtain edge ``e`` covers."""
    covered = max(0.0, min(member.glass_height, edge - member.top_offset))
    return covered / member.glass_height


@dataclass(frozen=True, slots=True)
class MemberShading:
    """What the geometry says for one member.

    - ``covered_fraction``: the part of its glass to cover, 0 to 1; ``None``
      in the simple mode, which knows no glass.
    - ``ideal_position``: the position on the glass scale, before calibration.
    - ``position``: the position on the motor scale, after calibration. This
      is the one to command.
    - ``end_position``: the conservative choice for a member that cannot take
      an intermediate position: closed as soon as ``position`` covers any
      glass. Whether it is used is the decision of the shading layer.
    """

    member_id: str
    covered_fraction: float | None
    ideal_position: Position
    position: Position
    end_position: Position

    def __post_init__(self) -> None:
        """Validate the types and the range of the fraction."""
        require_identifier(self.member_id, "the identifier of a member")
        if self.covered_fraction is not None:
            require_finite(self.covered_fraction, "the field 'covered_fraction'")
            if not 0.0 <= self.covered_fraction <= 1.0:
                raise ValueError("the field 'covered_fraction' must be within 0 and 1")
        for name in ("ideal_position", "position", "end_position"):
            require_type(getattr(self, name), Position, f"the field {name!r}")

    def to_data(self) -> JsonObject:
        """Return plain data."""
        return {
            "member_id": self.member_id,
            "covered_fraction": self.covered_fraction,
            "ideal_position": self.ideal_position.value,
            "position": self.position.value,
            "end_position": self.end_position.value,
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the value from plain data."""
        content = as_object(
            data,
            "member_id",
            "covered_fraction",
            "ideal_position",
            "position",
            "end_position",
        )

        def as_position(value: JsonValue) -> Position:
            return Position(as_int(value))

        return cls(
            member_id=read(content, "member_id", as_str),
            covered_fraction=read(content, "covered_fraction", optional(as_float)),
            ideal_position=read(content, "ideal_position", as_position),
            position=read(content, "position", as_position),
            end_position=read(content, "end_position", as_position),
        )


@dataclass(frozen=True, slots=True)
class ShadingGeometry:
    """The result of the geometry for one recompute.

    - ``sun``: whether the sun is on the window, and if not, why.
    - ``computed``: the positions follow from measurements; false in the
      simple mode.
    - ``ray_height``: the height above the floor, in metres, at which the ray
      that reaches exactly the permitted depth passes the glass. It is the
      quantity the decision is made in, the same for all members, and not
      clamped to the element. ``None`` while the sun is not on the window and
      in the simple mode.
    - ``curtain_edge``: the covered length ``e`` from the top of the element,
      along the glass, clamped to the element; ``None`` like the ray height.
    - ``members``: one entry per member, in the order of the element. While
      the sun is not on the window, the geometry asks for nothing: every
      member is open. That includes a window whose orientation is unknown.
    """

    sun: SunOnWindow
    computed: bool
    ray_height: float | None
    curtain_edge: float | None
    members: tuple[MemberShading, ...]

    def __post_init__(self) -> None:
        """Validate the types and that ray height and curtain edge come together."""
        require_type(self.sun, SunOnWindow, "the field 'sun'")
        require_type(self.computed, bool, "the flag 'computed'")
        for name in ("ray_height", "curtain_edge"):
            value = getattr(self, name)
            if value is not None:
                require_finite(value, f"the field {name!r}")
        if (self.ray_height is None) is not (self.curtain_edge is None):
            raise ValueError(
                "ray height and curtain edge are computed together "
                "(ray_height, curtain_edge)"
            )
        if self.curtain_edge is not None and self.curtain_edge < 0:
            raise ValueError("the field 'curtain_edge' must not be negative")
        object.__setattr__(self, "members", tuple(self.members))
        if not self.members:
            raise ValueError("the result names at least one member")
        for member in self.members:
            require_type(member, MemberShading, "a member of the result")
        require_unique(
            (member.member_id for member in self.members), "the members of the result"
        )

    def member(self, member_id: str) -> MemberShading:
        """Return the entry of one member."""
        for entry in self.members:
            if entry.member_id == member_id:
                return entry
        raise KeyError(member_id)

    def to_data(self) -> JsonObject:
        """Return plain data."""
        return {
            "sun": self.sun.to_data(),
            "computed": self.computed,
            "ray_height": self.ray_height,
            "curtain_edge": self.curtain_edge,
            "members": [member.to_data() for member in self.members],
        }

    @classmethod
    def from_data(cls, data: JsonValue) -> Self:
        """Rebuild the result from plain data."""
        content = as_object(
            data, "sun", "computed", "ray_height", "curtain_edge", "members"
        )
        return cls(
            sun=read(content, "sun", SunOnWindow.from_data),
            computed=read(content, "computed", as_bool),
            ray_height=read(content, "ray_height", optional(as_float)),
            curtain_edge=read(content, "curtain_edge", optional(as_float)),
            members=read(content, "members", tuple_of(MemberShading.from_data)),
        )


def members_for_edge(
    edge: float, members: Iterable[MemberGlass]
) -> tuple[MemberShading, ...]:
    """Return what every member does for one curtain edge ``e`` of the element."""
    require_finite(edge, "the curtain edge")
    if edge < 0:
        raise ValueError("the curtain edge must not be negative")
    result: list[MemberShading] = []
    for member in members:
        require_type(member, MemberGlass, "a member of an element")
        covered = covered_fraction(edge, member)
        position = position_for_cover(covered, member.calibration)
        result.append(
            MemberShading(
                member_id=member.member_id,
                covered_fraction=covered,
                ideal_position=ideal_position(covered),
                position=position,
                end_position=end_position_for(position),
            )
        )
    return tuple(result)


def _same_for_all(
    element: ShadedElement, position: Position, covered: float | None
) -> tuple[MemberShading, ...]:
    return tuple(
        MemberShading(
            member_id=member.member_id,
            covered_fraction=covered,
            ideal_position=position,
            position=position,
            end_position=end_position_for(position),
        )
        for member in element.members
    )


def compute_shading(sun: SunPosition, element: ShadedElement) -> ShadingGeometry:
    """Return where every member has to go so the sun enters no further than permitted.

    The one entry point for the shading layer, for the simple mode and the
    computed mode alike. It never raises for a sun position and an element
    that exist, and every position lies within 0 and 100.
    """
    require_type(sun, SunPosition, "the sun position")
    require_type(element, ShadedElement, "the element")
    settings = element.settings
    on_window = sun_on_window(sun, settings)
    measured = settings.use_measurements
    angle = on_window.horizontal_angle
    if not on_window.on_window or angle is None:
        members = _same_for_all(element, FULLY_OPEN, 0.0 if measured else None)
        return ShadingGeometry(on_window, measured, None, None, members)
    if not measured:
        members = _same_for_all(element, settings.fixed_position, None)
        return ShadingGeometry(on_window, measured, None, None, members)
    free = free_glass_length(sun.elevation, angle, settings)
    edge = curtain_edge(free, settings.element_height)
    return ShadingGeometry(
        sun=on_window,
        computed=True,
        ray_height=settings.element_bottom + free * sine(settings.pitch),
        curtain_edge=edge,
        members=members_for_edge(edge, element.members),
    )
