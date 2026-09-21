"""The measurements of shading as values: window, glass calibration, member glass.

``WindowConfig`` carries every window-level measurement as a flat field
``shading_<name>``, so that each can be inherited on its own;
``WindowConfig.geometry`` is the view over them, a
:class:`ShadingGeometrySettings`. The types here hold the value rules. The
one rule that spans several settings raises :class:`GeometryRuleError`;
``WindowConfig`` turns it into a ``SettingsCombinationError`` with the names
of its fields. The functions that compute with these values live in
``core/geometry``.

Conventions, stated once:

- Angles are in degrees. An azimuth runs clockwise from north (east is 90).
- ``orientation`` is the azimuth of the outward normal of the glass, projected
  onto the ground: the compass direction a person faces who looks out of the
  window.
- "Left" and "right" are meant as seen from inside, looking out.
- Lengths are in metres. Lengths on the glass are measured **along the
  glass**, also when it is tilted.
- ``pitch`` is the angle between the glass and the horizontal: 90 is vertical
  glass, 0 is glass that lies flat. The top edge of tilted glass leans into
  the room.
- A position is on the scale of the core model: 0 is closed, 100 is open.

Every value always has a value: a window without measurements is the normal
start, and the two switches say so (``use_measurements`` and
``orientation_known`` are off by default). Without an orientation the
geometry never says that the sun is on the window. The numbers behind a switch that
is off are checked on their own and otherwise ignored, so a user can switch
back and forth without clearing what was entered before.
"""

from dataclasses import dataclass, fields
from typing import Final

from ._validation import require_identifier, require_type
from .values import FULLY_CLOSED, FULLY_OPEN, Position

MAX_MEASURED_LENGTH: Final = 100.0
"""The longest length a measurement can state, in metres. Generous on purpose."""

MIN_CALIBRATION_SPAN: Final = 10
"""How far apart the two calibration positions are at least, in percent.

Between them the covered part of the glass is mapped linearly to whole
positions; with fewer steps the mapping would say nothing any more.
"""

MAX_AMPLIFICATION_CAP: Final = 10.0
"""The largest cap of the amplification for oblique sun."""

_FULL_CIRCLE: Final = 360.0
_HALF_CIRCLE: Final = 180.0
_RIGHT_ANGLE: Final = 90.0
_DEFAULT_FIXED_POSITION: Final = Position(30)
_LENGTH_TOLERANCE: Final = 1e-6
"""Two lengths that differ by less than a thousandth of a millimetre are equal."""


class GeometryRuleError(ValueError):
    """Measurements that are fine one by one contradict each other.

    ``fields`` names the settings the violated rule concerns, as fields of
    :class:`ShadingGeometrySettings`. ``WindowConfig`` turns it into a
    ``SettingsCombinationError`` with the names of its own fields.
    """

    def __init__(self, message: str, fields: tuple[str, ...]) -> None:
        """Keep the message and the fields the rule concerns."""
        super().__init__(f"{message} ({', '.join(fields)})")
        self.fields = fields


@dataclass(frozen=True, slots=True)
class _Range:
    """A range of numbers whose ends belong to it unless they are marked open."""

    low: float
    high: float
    open_low: bool = False
    open_high: bool = False

    def require(self, value: object, what: str) -> None:
        """Refuse everything that is not a number inside the range.

        The comparison also refuses "not a number" and infinity, and it never
        converts, so a whole number of any size is refused and not raised on.
        """
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"{what} must be a number, not {type(value).__name__}")
        above = value > self.low if self.open_low else value >= self.low
        below = value < self.high if self.open_high else value <= self.high
        if not (above and below):
            opening = "more than" if self.open_low else "at least"
            closing = "less than" if self.open_high else "at most"
            raise ValueError(
                f"{what} must be {opening} {self.low:g} and {closing} {self.high:g}"
            )


_AZIMUTH: Final = _Range(0.0, _FULL_CIRCLE, open_high=True)
_VIEW_LIMIT: Final = _Range(0.0, _HALF_CIRCLE, open_low=True)
_UP_TO_THE_RIGHT_ANGLE: Final = _Range(0.0, _RIGHT_ANGLE)
_LENGTH: Final = _Range(0.0, MAX_MEASURED_LENGTH)
_LENGTH_ABOVE_ZERO: Final = _Range(0.0, MAX_MEASURED_LENGTH, open_low=True)
_CAP: Final = _Range(1.0, MAX_AMPLIFICATION_CAP)


def _calibration_in_disorder(seat: Position, glass_top: Position) -> bool:
    return glass_top.value - seat.value < MIN_CALIBRATION_SPAN


_CALIBRATION_RULE: Final = (
    "the position at the upper glass end must lie at least "
    f"{MIN_CALIBRATION_SPAN} above the position at the seating point"
)


@dataclass(frozen=True, slots=True)
class GlassCalibration:
    """The glass calibration of one motor: two positions on the motor scale.

    - ``seat_position``: the position at which the curtain reaches the lower
      end of the free glass (the "seating point"). From here down, the glass
      is fully covered.
    - ``glass_top_position``: the position at which the lower edge of the
      curtain reaches the upper end of the glass. From here up, the glass is
      fully free.

    0 is closed and 100 is open, so the seating point is the **smaller**
    number. The defaults mean "no calibration": the full range.
    """

    seat_position: Position = FULLY_CLOSED
    glass_top_position: Position = FULLY_OPEN

    def __post_init__(self) -> None:
        """Validate the two positions, then their order."""
        require_type(self.seat_position, Position, "the field 'seat_position'")
        require_type(
            self.glass_top_position, Position, "the field 'glass_top_position'"
        )
        if _calibration_in_disorder(self.seat_position, self.glass_top_position):
            raise ValueError(f"{_CALIBRATION_RULE} (seat_position, glass_top_position)")

    @property
    def span(self) -> int:
        """Return the number of positions between the two calibration points."""
        return self.glass_top_position.value - self.seat_position.value


NO_CALIBRATION: Final = GlassCalibration()
"""The calibration that changes nothing."""


@dataclass(frozen=True, slots=True)
class MemberGlass:
    """The glass of one member inside the element, with its calibration.

    - ``glass_height``: the height of the member's glass, along the glass.
    - ``top_offset``: how far the top edge of the member's glass lies below
      the top of the element, along the glass. Members that sit side by side
      at the same height have the same offset; a member without an offset
      has offset 0.
    - ``calibration``: the glass calibration of the member's motor.
    """

    member_id: str
    glass_height: float
    top_offset: float = 0.0
    calibration: GlassCalibration = NO_CALIBRATION

    def __post_init__(self) -> None:
        """Validate the identifier, the two lengths and the calibration."""
        require_identifier(self.member_id, "the identifier of a member")
        _LENGTH_ABOVE_ZERO.require(
            self.glass_height, "the field 'glass_height' of a member"
        )
        _LENGTH.require(self.top_offset, "the field 'top_offset' of a member")
        require_type(
            self.calibration, GlassCalibration, "the field 'calibration' of a member"
        )

    def fits_into(self, element_height: float) -> bool:
        """Return whether the member's glass lies inside an element of that height."""
        return self.top_offset + self.glass_height <= element_height + _LENGTH_TOLERANCE


@dataclass(frozen=True, slots=True)
class ShadingGeometrySettings:
    """The window-level measurements of shading; every field always has a value.

    - ``use_measurements``: off (the default) is the simple mode: shading
      drives to ``fixed_position``. On: the position is computed from the
      measurements below.
    - ``fixed_position``: the shading position of the simple mode, on the
      motor scale.
    - ``orientation_known``: whether ``orientation`` was stated. **Shading
      needs the orientation.** Off (the default): nobody can say whether the
      sun is on the window, so it is not, in the simple mode and in the
      computed mode alike; nothing is assumed in its place.
    - ``orientation``: azimuth of the outward normal, 0 up to (not including)
      360.
    - ``view_left``, ``view_right``: how far to the left and to the right of
      the normal the sun can still reach the window, seen from inside looking
      out; more than 0, at most 180. Vertical glass never sees beyond 90.
    - ``min_elevation``: the sun has to stand at least this high for shading
      to **start** (horizon obstruction). ``end_elevation``: below this
      elevation the sun is no longer on the window and shading ends. Both
      from 0 to 90. Shading never starts below the end elevation either, so
      the higher of the two is what a start needs (:attr:`start_elevation`);
      the two need no order, and each can be inherited on its own.
    - ``element_bottom``: the height of the lower edge of the glass of the
      element above the floor. ``element_height``: the height of the element
      along the glass, from that lower edge to the top of the topmost glass.
    - ``depth``: how far the sun may shine into the room, measured on the
      floor, perpendicular to the façade, from the point below the lower edge
      of the glass.
    - ``pitch``: 90 is vertical glass; see the module.
    - ``amplification_cap``: the more obliquely the sun strikes the façade,
      the higher the shutter may stay, by the factor 1 / cos(horizontal
      angle). The factor is capped here, because close to the façade plane it
      grows without bound and an error of a few degrees in the orientation
      changes it a lot. The default 2 is reached at 60 degrees.
    - ``calibration_seat``, ``calibration_glass_top``: the glass calibration
      that the members of the window use unless they state their own.
    """

    use_measurements: bool = False
    fixed_position: Position = _DEFAULT_FIXED_POSITION
    orientation_known: bool = False
    orientation: float = 180.0
    view_left: float = 90.0
    view_right: float = 90.0
    min_elevation: float = 0.0
    end_elevation: float = 0.0
    element_bottom: float = 0.9
    element_height: float = 1.2
    depth: float = 0.5
    pitch: float = 90.0
    amplification_cap: float = 2.0
    calibration_seat: Position = FULLY_CLOSED
    calibration_glass_top: Position = FULLY_OPEN

    def __post_init__(self) -> None:
        """Validate every value on its own, then the rules over several of them."""
        require_type(self.use_measurements, bool, "the switch 'use_measurements'")
        require_type(self.fixed_position, Position, "the field 'fixed_position'")
        require_type(self.orientation_known, bool, "the switch 'orientation_known'")
        ranges = {
            "orientation": _AZIMUTH,
            "view_left": _VIEW_LIMIT,
            "view_right": _VIEW_LIMIT,
            "min_elevation": _UP_TO_THE_RIGHT_ANGLE,
            "end_elevation": _UP_TO_THE_RIGHT_ANGLE,
            "pitch": _UP_TO_THE_RIGHT_ANGLE,
            "element_bottom": _LENGTH,
            "element_height": _LENGTH_ABOVE_ZERO,
            "depth": _LENGTH,
            "amplification_cap": _CAP,
        }
        for name, allowed in ranges.items():
            allowed.require(getattr(self, name), f"the field {name!r}")
        require_type(self.calibration_seat, Position, "the field 'calibration_seat'")
        require_type(
            self.calibration_glass_top, Position, "the field 'calibration_glass_top'"
        )
        violated = self.violated_rules
        if violated:
            raise GeometryRuleError(*violated[0])

    @property
    def violated_rules(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Return the violated rules over several settings: message and fields."""
        found: list[tuple[str, tuple[str, ...]]] = []
        if _calibration_in_disorder(self.calibration_seat, self.calibration_glass_top):
            found.append(
                (_CALIBRATION_RULE, ("calibration_seat", "calibration_glass_top"))
            )
        return tuple(found)

    @property
    def start_elevation(self) -> float:
        """Return the elevation a start of shading needs: the higher of the two."""
        return max(self.min_elevation, self.end_elevation)

    @property
    def calibration(self) -> GlassCalibration:
        """Return the calibration of the window as one value."""
        return GlassCalibration(self.calibration_seat, self.calibration_glass_top)


GEOMETRY_FIELDS: Final = tuple(entry.name for entry in fields(ShadingGeometrySettings))
"""The fields of the view; with ``shading_`` in front, the flat settings."""

GEOMETRY_PREFIX: Final = "shading_"
"""What stands in front of a field of the view in the name of its flat setting."""


MEMBER_MEASUREMENT_FIELDS: Final = (
    "glass_height",
    "top_offset",
    "calibration_seat",
    "calibration_glass_top",
)
"""What a member can state itself; also the keys of the member-level settings."""


class MemberGlassError(ValueError):
    """What a member states does not fit together with what applies to it.

    Each value may be fine on its own. ``member_id`` names the member and
    ``fields`` the measurements the violated rule concerns, as fields of
    :class:`MemberMeasurements`.
    """

    def __init__(self, message: str, member_id: str, fields: tuple[str, ...]) -> None:
        """Keep the message, the member and the fields the rule concerns."""
        if not fields:
            raise ValueError("a rule over several measurements names its fields")
        super().__init__(f"{message} (member {member_id!r}: {', '.join(fields)})")
        self.member_id = member_id
        self.fields = fields


@dataclass(frozen=True, slots=True)
class MemberMeasurements:
    """What one member states itself; ``None`` means that it states nothing.

    A member inherits the measurements of its window unless it states its
    own: its glass is as high as the element, its top edge has the offset 0,
    and its motor has the calibration of the window. ``None`` is not a value
    of any of these measurements, so it can say "not stated" here. Every
    stated value is checked on its own; what has to fit together is judged
    by :func:`member_glass_for`.
    """

    glass_height: float | None = None
    top_offset: float | None = None
    calibration_seat: Position | None = None
    calibration_glass_top: Position | None = None

    def __post_init__(self) -> None:
        """Validate every stated value on its own."""
        if self.glass_height is not None:
            _LENGTH_ABOVE_ZERO.require(
                self.glass_height, "the field 'glass_height' of a member"
            )
        if self.top_offset is not None:
            _LENGTH.require(self.top_offset, "the field 'top_offset' of a member")
        for name in ("calibration_seat", "calibration_glass_top"):
            value = getattr(self, name)
            if value is not None:
                require_type(value, Position, f"the field {name!r} of a member")

    @property
    def stated(self) -> tuple[str, ...]:
        """Return the fields the member states itself."""
        return tuple(
            name
            for name in MEMBER_MEASUREMENT_FIELDS
            if getattr(self, name) is not None
        )


NO_MEASUREMENTS: Final = MemberMeasurements()
"""A member that states nothing: everything is inherited from the window."""


def member_glass_for(
    window: ShadingGeometrySettings, member_id: str, stated: MemberMeasurements
) -> MemberGlass:
    """Return the glass that applies to a member: its own values, else the window's.

    Two rules span several values, and both raise :class:`MemberGlassError`
    with the fields the **member** states among those concerned, because the
    values of the window are fine among themselves: the calibration points
    in order and apart, and the glass inside the element.
    """
    require_type(window, ShadingGeometrySettings, "the measurements of the window")
    require_type(stated, MemberMeasurements, "the measurements of a member")
    seat = _own_or(stated.calibration_seat, window.calibration_seat)
    glass_top = _own_or(stated.calibration_glass_top, window.calibration_glass_top)
    if _calibration_in_disorder(seat, glass_top):
        pair = ("calibration_seat", "calibration_glass_top")
        raise MemberGlassError(
            _CALIBRATION_RULE, member_id, _stated_among(stated, pair)
        )
    glass = MemberGlass(
        member_id,
        glass_height=_own_or(stated.glass_height, window.element_height),
        top_offset=_own_or(stated.top_offset, 0.0),
        calibration=GlassCalibration(seat, glass_top),
    )
    if not glass.fits_into(window.element_height):
        raise MemberGlassError(
            "the glass of the member reaches below the element: its top offset "
            "plus its glass height must not exceed the element height of the "
            "window; a member that states an offset states its glass height too",
            member_id,
            _stated_among(stated, ("glass_height", "top_offset")),
        )
    return glass


def _own_or[T](own: T | None, inherited: T) -> T:
    return inherited if own is None else own


def _stated_among(
    stated: MemberMeasurements, names: tuple[str, ...]
) -> tuple[str, ...]:
    return tuple(name for name in names if name in stated.stated)
