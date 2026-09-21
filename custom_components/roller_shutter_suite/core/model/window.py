"""Window configuration as the core sees it: members and their capabilities."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import time, timedelta
from enum import StrEnum, unique
from typing import Final

from ._validation import (
    require_finite,
    require_identifier,
    require_type,
    require_unique,
)
from .functions import FaultBehavior, FunctionId
from .geometry import (
    GEOMETRY_FIELDS,
    GEOMETRY_PREFIX,
    NO_MEASUREMENTS,
    GeometryRuleError,
    MemberGlass,
    MemberMeasurements,
    ShadingGeometrySettings,
    member_glass_for,
)
from .schedule import (
    TRIGGER_FIELDS,
    DayTriggers,
    ScheduleProfile,
    ScheduleRuleError,
    ScheduleSettings,
    ScheduleTargets,
    Trigger,
    TriggerKind,
)
from .values import FULLY_CLOSED, FULLY_OPEN, Position

SCHEDULE_DAY_TYPES: Final = ("workday", "weekend", "holiday")
"""The day types as they appear in the names of the schedule's settings."""

SCHEDULE_EDGES: Final = ("morning", "evening")
"""The two triggers of a day as they appear in the names of the settings."""

# --- The built-in defaults of the schedule: this is the one place ---------------------
_SCHEDULE_ENABLED: Final = True
_MORNING_KIND: Final = TriggerKind.FIXED_TIME
_MORNING_TIME_WORKDAY: Final = time(7, 0)
_MORNING_TIME_FREE_DAY: Final = time(8, 30)
_MORNING_NOT_BEFORE: Final = time(6, 0)
_MORNING_NOT_AFTER: Final = time(9, 0)
_EVENING_KIND: Final = TriggerKind.SUN_EVENT
_EVENING_TIME: Final = time(20, 0)
_EVENING_NOT_BEFORE: Final = time(17, 0)
_EVENING_NOT_AFTER: Final = time(22, 0)
_SUN_OFFSET_MINUTES: Final = 0
_ELEVATION: Final = 0.0
_MORNING_POSITION: Final = FULLY_OPEN
_EVENING_POSITION: Final = FULLY_CLOSED
_EVENING_POSITION_SUMMER: Final = FULLY_CLOSED
_SUMMER_FIRST_DAY: Final = (5, 1)
_SUMMER_LAST_DAY: Final = (9, 30)
_BRIGHTNESS_THRESHOLD: Final = 50.0  # lux
_BRIGHTNESS_DELAY: Final = timedelta(minutes=10)
_RANDOM_OFFSET: Final = timedelta(0)
# ---------------------------------------------------------------------------------------

MIN_TOLERANCE: Final = 1
DEFAULT_TOLERANCE_CALCULATED: Final = 2
DEFAULT_TOLERANCE_MEASURED: Final = 3
_MAX_TOLERANCE: Final = 100
_DEFAULT_FROST_POSITION: Final = Position(90)
_DEFAULT_REEVALUATE_AFTER: Final = timedelta(minutes=5)
_DEFAULT_MIN_INTERVAL: Final = timedelta(minutes=10)
_GEOMETRY: Final = ShadingGeometrySettings()
"""The built-in defaults of the measurements of shading stand at the view."""


@unique
class CoveringType(StrEnum):
    """What hangs in front of the glass. Only roller shutters are implemented."""

    ROLLER_SHUTTER = "roller_shutter"


@unique
class PositionSource(StrEnum):
    """Where a reported position comes from; stated by the user."""

    MEASURED = "measured"
    """The drive itself measures the position."""
    CALCULATED = "calculated"
    """The actuator calculates the position from run time."""


@unique
class TransitReporting(StrEnum):
    """Whether a member reports that it is opening or closing."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"
    """Not observed yet."""


@unique
class PositionUpdates(StrEnum):
    """When a member reports its position during a movement."""

    LIVE = "live"
    END_ONLY = "end_only"


@unique
class CapabilityState(StrEnum):
    """Whether the members of a window have a capability.

    ``UNKNOWN`` is not ``MISSING``: nothing was ever known, not even a last
    state, so nothing may be concluded from it.
    """

    PRESENT = "present"
    MISSING = "missing"
    UNKNOWN = "unknown"


_CAPABILITY_FLAGS: Final = (
    "supports_open_close",
    "supports_set_position",
    "supports_stop",
    "reports_position",
)


@dataclass(frozen=True, slots=True)
class CapabilityProfile:
    """What a member can do and report.

    A member that reports no position or cannot be set to a position is valid;
    it is operated in a degraded mode. Travel times are configuration values
    and are never learned from reports.

    ``stated_tolerance`` is the tolerance the user stated for comparing a
    reported position with a target, or ``None``. :attr:`tolerance` is the one
    that applies: the stated one, else 2 for a calculated position (the report
    equals the command, so a deviation means an intervention) and 3 for a
    measured one. The minimum is 1.

    ``capabilities_known`` is ``False`` only when **nothing** is known about
    what the member can do, not even a last state: a member that was never
    seen. The four capability flags then carry no information, and to make
    that unmistakable they must all be off; a profile that claims a capability
    it does not know is refused. :meth:`capability_state` answers ``UNKNOWN``.
    All four flags come from the same report of the member, so they are known
    or unknown together.

    A member that merely cannot be reached at present is **not** unknown: its
    last known capabilities apply, and whoever builds the profile hands them
    in as known.
    """

    supports_open_close: bool
    supports_set_position: bool
    supports_stop: bool
    reports_position: bool
    travel_time_up: timedelta
    travel_time_down: timedelta
    position_source: PositionSource = PositionSource.CALCULATED
    reports_transit_states: TransitReporting = TransitReporting.UNKNOWN
    position_updates: PositionUpdates = PositionUpdates.END_ONLY
    report_delay: timedelta = timedelta(0)
    stated_tolerance: int | None = None
    capabilities_known: bool = True

    def __post_init__(self) -> None:
        """Validate types and durations."""
        for name in (*_CAPABILITY_FLAGS, "capabilities_known"):
            require_type(getattr(self, name), bool, f"the capability {name!r}")
        if not self.capabilities_known and any(
            getattr(self, name) for name in _CAPABILITY_FLAGS
        ):
            raise ValueError(
                "a profile whose capabilities are not known must not claim a "
                "capability; hand the last known capabilities in as known"
            )
        require_type(self.position_source, PositionSource, "the position source")
        require_type(
            self.reports_transit_states, TransitReporting, "the transit reporting"
        )
        require_type(self.position_updates, PositionUpdates, "the position updates")
        for name in ("travel_time_up", "travel_time_down"):
            travel_time = getattr(self, name)
            require_type(travel_time, timedelta, f"the {name!r}")
            if travel_time <= timedelta(0):
                raise ValueError(f"the {name!r} must be longer than zero")
        require_type(self.report_delay, timedelta, "the report delay")
        if self.report_delay < timedelta(0):
            raise ValueError("the report delay must not be negative")
        if self.stated_tolerance is not None:
            if isinstance(self.stated_tolerance, bool) or not isinstance(
                self.stated_tolerance, int
            ):
                raise TypeError("the tolerance must be an integer")
            if not MIN_TOLERANCE <= self.stated_tolerance <= _MAX_TOLERANCE:
                raise ValueError("the tolerance must be within 1 and 100")

    @property
    def tolerance(self) -> int:
        """Return the tolerance that applies to this member."""
        if self.stated_tolerance is not None:
            return self.stated_tolerance
        if self.position_source is PositionSource.MEASURED:
            return DEFAULT_TOLERANCE_MEASURED
        return DEFAULT_TOLERANCE_CALCULATED

    def capability_state(self, name: str) -> CapabilityState:
        """Return the state of one capability flag, given by its field name.

        While nothing is known about the member, every flag is ``UNKNOWN``.
        """
        if name not in _CAPABILITY_FLAGS:
            raise ValueError(f"{name!r} is not a capability")
        if not self.capabilities_known:
            return CapabilityState.UNKNOWN
        if getattr(self, name):
            return CapabilityState.PRESENT
        return CapabilityState.MISSING


@dataclass(frozen=True, slots=True)
class WindowCapabilities:
    """The capabilities of a window: the lowest common denominator of its members.

    **These booleans cannot tell "missing" from "unknown".** A member about
    which nothing is known carries no capability flag, so every flag of a
    window with such a member reads ``False``, also when all other members
    have the capability. Code that decides anything from a ``False`` must use
    :class:`WindowCapabilityStates` (``WindowConfig.capability_states``).
    """

    supports_open_close: bool
    supports_set_position: bool
    supports_stop: bool
    reports_position: bool

    def __post_init__(self) -> None:
        """Validate the flags."""
        for name in _CAPABILITY_FLAGS:
            require_type(getattr(self, name), bool, f"the capability {name!r}")


@dataclass(frozen=True, slots=True)
class WindowCapabilityStates:
    """The capabilities of a window in three states, over all its members.

    ``MISSING`` if any member definitely lacks the capability; otherwise
    ``UNKNOWN`` if the capabilities of any member are not known; otherwise
    ``PRESENT``. "Missing" takes precedence, because a single member that
    cannot do something settles the question for the window.
    """

    supports_open_close: CapabilityState
    supports_set_position: CapabilityState
    supports_stop: CapabilityState
    reports_position: CapabilityState

    def __post_init__(self) -> None:
        """Validate the states."""
        for name in _CAPABILITY_FLAGS:
            require_type(
                getattr(self, name), CapabilityState, f"the capability {name!r}"
            )


@dataclass(frozen=True, slots=True)
class TemperatureTier:
    """One tier of the temperature condition of shading: threshold and hysteresis."""

    threshold: float
    hysteresis: float

    def __post_init__(self) -> None:
        """Validate the numbers."""
        require_finite(self.threshold, "the threshold of a temperature tier")
        require_finite(self.hysteresis, "the hysteresis of a temperature tier")
        if self.hysteresis < 0:
            raise ValueError(
                "the hysteresis of a temperature tier must not be negative"
            )


class SettingsCombinationError(ValueError):
    """A rule that spans several settings refuses their combination.

    Each of the values may be fine on its own. **Contract for every block that
    adds such a rule to** :class:`WindowConfig`: raise this error, and name in
    ``keys`` exactly the fields the rule concerns. The inheritance resolver
    then treats those keys, and no others, as faulty, each by the fault
    behavior of its function. A rule that raises anything else for a
    combination cannot be attributed, and the resolver has to pause every
    pausable function of the window instead.
    """

    def __init__(self, message: str, keys: Iterable[str]) -> None:
        """Keep the message and the keys the rule concerns."""
        super().__init__(message)
        self.keys: tuple[str, ...] = tuple(keys)
        if not self.keys:
            raise ValueError("a rule over several settings names the keys it concerns")
        for key in self.keys:
            require_identifier(key, "a key of a rule over several settings")


@dataclass(frozen=True, slots=True)
class MotorProtectionSettings:
    """Motor protection: it applies to comfort movements only.

    A view over the fields ``motor_min_change`` and ``motor_min_interval`` of
    ``WindowConfig``, which are inherited one by one; it holds their rules.

    ``min_change`` is the smallest change of position, in percent, that is
    worth a movement; ``min_interval`` the shortest time between two own
    comfort movements. Zero switches a part off.
    """

    min_change: int = 5
    min_interval: timedelta = _DEFAULT_MIN_INTERVAL

    def __post_init__(self) -> None:
        """Validate the ranges."""
        if isinstance(self.min_change, bool) or not isinstance(self.min_change, int):
            raise TypeError("the minimum change must be an integer")
        if not 0 <= self.min_change <= _MAX_TOLERANCE:
            raise ValueError("the minimum change must be within 0 and 100")
        require_type(self.min_interval, timedelta, "the minimum interval")
        if self.min_interval < timedelta(0):
            raise ValueError("the minimum interval must not be negative")


@dataclass(frozen=True, slots=True)
class FrostSettings:
    """Frost protection of one window.

    A view over the ``frost_*`` fields of ``WindowConfig``, which are
    inherited one by one; it holds their value rules.

    - ``source``: key of the temperature source; ``None`` means that frost
      protection is not configured.
    - Frost is active below ``threshold``; it ends at ``threshold`` plus
      ``hysteresis``.
    - ``position``: how far own movements open while frost is active.
    - ``applies_to_protection``: whether protection movements are limited too;
      comfort movements always are, fire never is.
    - ``hold_closed``: the option "do not raise a closed window at all".
    """

    source: str | None = None
    threshold: float = 0.0
    hysteresis: float = 1.0
    position: Position = _DEFAULT_FROST_POSITION
    applies_to_protection: bool = False
    hold_closed: bool = False

    def __post_init__(self) -> None:
        """Validate the types and the numbers."""
        if self.source is not None:
            require_identifier(self.source, "the frost source")
        require_finite(self.threshold, "the frost threshold")
        require_finite(self.hysteresis, "the frost hysteresis")
        if self.hysteresis < 0:
            raise ValueError("the frost hysteresis must not be negative")
        require_type(self.position, Position, "the frost position")
        require_type(
            self.applies_to_protection, bool, "the flag 'applies to protection'"
        )
        require_type(self.hold_closed, bool, "the flag 'hold closed'")


@dataclass(frozen=True, slots=True)
class MemberConfig:
    """One cover of a window as the core sees it.

    ``measurements`` is what the member states itself for geometric shading
    (glass height, top offset, glass calibration); by default nothing, and
    the member inherits the measurements of its window. The inheritance
    resolver fills it from the member-level settings, with sound values only.
    """

    member_id: str
    capabilities: CapabilityProfile
    measurements: MemberMeasurements = NO_MEASUREMENTS

    def __post_init__(self) -> None:
        """Validate the member identifier."""
        require_identifier(self.member_id, "the identifier of a member")
        require_type(
            self.capabilities, CapabilityProfile, "the capability profile of a member"
        )
        require_type(
            self.measurements, MemberMeasurements, "the measurements of a member"
        )


@dataclass(frozen=True, slots=True)
class WindowConfig:
    """The configuration of one window after inheritance has been resolved.

    This block defines the parts all later blocks share: identity, covering
    type, members and the doors kept open. The blocks that build a feature add
    its settings.

    - ``morning_condition_source``: key of the source that has to hold before
      the morning opening (conditional morning opening). ``None`` means the
      condition is always fulfilled. No rule reads it yet.
    - ``shading_temperature_tiers``: the temperature condition of shading as a
      list of tiers. Only zero (no temperature condition) or one entry are
      accepted at present.
    - ``schedule_profile``: the key under which the schedule's targets are
      looked up; it has one value.
    - ``frost_source``, ``frost_threshold``, ``frost_hysteresis``,
      ``frost_position``, ``frost_applies_to_protection``,
      ``frost_hold_closed``: the settings of frost protection, one field per
      setting so that each can be inherited on its own; :attr:`frost` is the
      view over them. Without a source, frost protection is not configured.
    - ``motor_min_change`` and ``motor_min_interval``: the settings of motor
      protection; :attr:`motor_protection` is the view over them.
    - ``reevaluate_after``: the upper bound of a deferral whose end is not
      known: that long after the recompute, at the latest, the window is
      evaluated again.
    - ``schedule_enabled`` and the other ``schedule_*`` fields: the settings of
      the schedule, one field per setting; :attr:`schedule` is the view over
      them and describes them. Per day type (workday, weekend, holiday) and
      per edge (morning, evening) there are the six fields of a ``Trigger``.
      ``schedule_brightness_threshold`` is **in lux**, the unit the
      brightness source has to report in. The built-in defaults of all of
      them stand in one block at the top of this module.
    - ``shading_use_measurements`` and the other ``shading_*`` measurements:
      the window-level measurements of geometric shading, one field per
      setting; :attr:`geometry` is the view over them and describes them,
      with units and conventions. Their built-in defaults stand at the view
      and mean "no measurements": the simple mode with a fixed position.
      What a member states itself lives with the member
      (``MemberConfig.measurements``); :attr:`member_glass` is the glass
      that applies to every member.
    - ``disabled_functions``: the functions that are paused for this window
      because a stored setting of theirs is faulty (the inheritance resolver
      fills it; it is never stored). The arbiter skips the layers of such a
      function and says so in the decision. Only a function whose fault
      behavior is "pause" is accepted: whatever protects or restricts
      movement can never be switched off by a data fault.
    """

    window_id: str
    members: tuple[MemberConfig, ...]
    covering_type: CoveringType = CoveringType.ROLLER_SHUTTER
    morning_condition_source: str | None = None
    shading_temperature_tiers: tuple[TemperatureTier, ...] = ()
    schedule_profile: ScheduleProfile = ScheduleProfile.DEFAULT
    frost_source: str | None = None
    frost_threshold: float = 0.0
    frost_hysteresis: float = 1.0
    frost_position: Position = _DEFAULT_FROST_POSITION
    frost_applies_to_protection: bool = False
    frost_hold_closed: bool = False
    motor_min_change: int = 5
    motor_min_interval: timedelta = _DEFAULT_MIN_INTERVAL
    reevaluate_after: timedelta = _DEFAULT_REEVALUATE_AFTER
    schedule_enabled: bool = _SCHEDULE_ENABLED
    schedule_workday_morning_kind: TriggerKind = _MORNING_KIND
    schedule_workday_morning_time: time = _MORNING_TIME_WORKDAY
    schedule_workday_morning_offset_minutes: int = _SUN_OFFSET_MINUTES
    schedule_workday_morning_elevation: float = _ELEVATION
    schedule_workday_morning_not_before: time = _MORNING_NOT_BEFORE
    schedule_workday_morning_not_after: time = _MORNING_NOT_AFTER
    schedule_workday_evening_kind: TriggerKind = _EVENING_KIND
    schedule_workday_evening_time: time = _EVENING_TIME
    schedule_workday_evening_offset_minutes: int = _SUN_OFFSET_MINUTES
    schedule_workday_evening_elevation: float = _ELEVATION
    schedule_workday_evening_not_before: time = _EVENING_NOT_BEFORE
    schedule_workday_evening_not_after: time = _EVENING_NOT_AFTER
    schedule_weekend_morning_kind: TriggerKind = _MORNING_KIND
    schedule_weekend_morning_time: time = _MORNING_TIME_FREE_DAY
    schedule_weekend_morning_offset_minutes: int = _SUN_OFFSET_MINUTES
    schedule_weekend_morning_elevation: float = _ELEVATION
    schedule_weekend_morning_not_before: time = _MORNING_NOT_BEFORE
    schedule_weekend_morning_not_after: time = _MORNING_NOT_AFTER
    schedule_weekend_evening_kind: TriggerKind = _EVENING_KIND
    schedule_weekend_evening_time: time = _EVENING_TIME
    schedule_weekend_evening_offset_minutes: int = _SUN_OFFSET_MINUTES
    schedule_weekend_evening_elevation: float = _ELEVATION
    schedule_weekend_evening_not_before: time = _EVENING_NOT_BEFORE
    schedule_weekend_evening_not_after: time = _EVENING_NOT_AFTER
    schedule_holiday_morning_kind: TriggerKind = _MORNING_KIND
    schedule_holiday_morning_time: time = _MORNING_TIME_FREE_DAY
    schedule_holiday_morning_offset_minutes: int = _SUN_OFFSET_MINUTES
    schedule_holiday_morning_elevation: float = _ELEVATION
    schedule_holiday_morning_not_before: time = _MORNING_NOT_BEFORE
    schedule_holiday_morning_not_after: time = _MORNING_NOT_AFTER
    schedule_holiday_evening_kind: TriggerKind = _EVENING_KIND
    schedule_holiday_evening_time: time = _EVENING_TIME
    schedule_holiday_evening_offset_minutes: int = _SUN_OFFSET_MINUTES
    schedule_holiday_evening_elevation: float = _ELEVATION
    schedule_holiday_evening_not_before: time = _EVENING_NOT_BEFORE
    schedule_holiday_evening_not_after: time = _EVENING_NOT_AFTER
    schedule_morning_position: Position = _MORNING_POSITION
    schedule_evening_position: Position = _EVENING_POSITION
    schedule_evening_position_summer: Position = _EVENING_POSITION_SUMMER
    schedule_workday_source: str | None = None
    schedule_holiday_source: str | None = None
    schedule_season_source: str | None = None
    schedule_summer_by_date: bool = False
    schedule_summer_first_day: tuple[int, int] = _SUMMER_FIRST_DAY
    schedule_summer_last_day: tuple[int, int] = _SUMMER_LAST_DAY
    schedule_brightness_source: str | None = None
    schedule_brightness_threshold: float = _BRIGHTNESS_THRESHOLD
    schedule_brightness_delay: timedelta = _BRIGHTNESS_DELAY
    schedule_random_offset: timedelta = _RANDOM_OFFSET
    shading_use_measurements: bool = _GEOMETRY.use_measurements
    shading_fixed_position: Position = _GEOMETRY.fixed_position
    shading_orientation_known: bool = _GEOMETRY.orientation_known
    shading_orientation: float = _GEOMETRY.orientation
    shading_view_left: float = _GEOMETRY.view_left
    shading_view_right: float = _GEOMETRY.view_right
    shading_min_elevation: float = _GEOMETRY.min_elevation
    shading_end_elevation: float = _GEOMETRY.end_elevation
    shading_element_bottom: float = _GEOMETRY.element_bottom
    shading_element_height: float = _GEOMETRY.element_height
    shading_depth: float = _GEOMETRY.depth
    shading_pitch: float = _GEOMETRY.pitch
    shading_amplification_cap: float = _GEOMETRY.amplification_cap
    shading_calibration_seat: Position = _GEOMETRY.calibration_seat
    shading_calibration_glass_top: Position = _GEOMETRY.calibration_glass_top
    disabled_functions: frozenset[FunctionId] = frozenset()

    def __post_init__(self) -> None:
        """Validate identity, members and the doors kept open."""
        require_identifier(self.window_id, "the identifier of a window")
        object.__setattr__(self, "members", tuple(self.members))
        object.__setattr__(
            self, "shading_temperature_tiers", tuple(self.shading_temperature_tiers)
        )
        if not self.members:
            raise ValueError("a window has at least one member")
        for member in self.members:
            require_type(member, MemberConfig, "a member of a window")
        require_unique(
            (member.member_id for member in self.members), "the members of a window"
        )
        require_type(self.covering_type, CoveringType, "the covering type")
        if self.morning_condition_source is not None:
            require_identifier(
                self.morning_condition_source, "the source of the morning condition"
            )
        for tier in self.shading_temperature_tiers:
            require_type(tier, TemperatureTier, "a temperature tier")
        if len(self.shading_temperature_tiers) > 1:
            raise ValueError("more than one temperature tier is not supported yet")
        require_type(self.schedule_profile, ScheduleProfile, "the schedule profile")
        # The views validate the single values of frost and motor protection.
        _ = (self.frost, self.motor_protection)
        require_type(self.reevaluate_after, timedelta, "the re-evaluation bound")
        if self.reevaluate_after <= timedelta(0):
            raise ValueError("the re-evaluation bound must be longer than zero")
        given: object = self.disabled_functions
        if isinstance(given, str):
            raise TypeError("the disabled functions must be a set of identifiers")
        object.__setattr__(
            self, "disabled_functions", frozenset(self.disabled_functions)
        )
        for function in self.disabled_functions:
            require_type(function, FunctionId, "a disabled function")
            if function.fault_behavior is not FaultBehavior.PAUSE:
                raise ValueError(
                    f"the function {function.value!r} falls back on a fault; it "
                    "can never be switched off"
                )
        # Last, because these views end with rules over several settings.
        refused = self._refused_combination()
        if refused is not None:
            raise refused

    def _refused_combination(self) -> SettingsCombinationError | None:
        """Build the views that have rules over several settings; return a refusal.

        Each view checks every single value first and only then its rules. A
        refused rule of the first view waits until the single values of the
        second are checked too, and those raise from here: a rule must never
        hide an invalid single value. The first refused rule is returned.
        """
        refused: SettingsCombinationError | None = None
        try:
            _ = self.geometry
        except GeometryRuleError as err:
            refused = SettingsCombinationError(
                str(err), [f"{GEOMETRY_PREFIX}{field}" for field in err.fields]
            )
        try:
            _ = self.schedule
        except ScheduleRuleError as err:
            if refused is None:
                refused = SettingsCombinationError(
                    str(err), [f"schedule_{field}" for field in err.fields]
                )
        if refused is None:
            # What the members state has to fit the measurements of the
            # window; a ``MemberGlassError`` names the member and its fields.
            _ = self.member_glass
        return refused

    def _schedule_trigger(self, day_type: str, edge: str) -> Trigger:
        values = {
            field: getattr(self, f"schedule_{day_type}_{edge}_{field}")
            for field in TRIGGER_FIELDS
        }
        return Trigger(**values)

    @property
    def schedule(self) -> ScheduleSettings:
        """Return the settings of the schedule as one value.

        The targets are filed under the profile key of the window; the key
        has one value.
        """
        workday, weekend, holiday = (
            DayTriggers(
                *(self._schedule_trigger(day_type, edge) for edge in SCHEDULE_EDGES)
            )
            for day_type in SCHEDULE_DAY_TYPES
        )
        targets = ScheduleTargets(
            morning_position=self.schedule_morning_position,
            evening_position=self.schedule_evening_position,
            evening_position_summer=self.schedule_evening_position_summer,
        )
        return ScheduleSettings(
            enabled=self.schedule_enabled,
            workday=workday,
            weekend=weekend,
            holiday=holiday,
            targets={self.schedule_profile: targets},
            workday_source=self.schedule_workday_source,
            holiday_source=self.schedule_holiday_source,
            season_source=self.schedule_season_source,
            summer_by_date=self.schedule_summer_by_date,
            summer_first_day=self.schedule_summer_first_day,
            summer_last_day=self.schedule_summer_last_day,
            brightness_source=self.schedule_brightness_source,
            brightness_threshold=self.schedule_brightness_threshold,
            brightness_delay=self.schedule_brightness_delay,
            random_offset=self.schedule_random_offset,
        )

    @property
    def geometry(self) -> ShadingGeometrySettings:
        """Return the window-level measurements of shading as one value."""
        values = {
            name: getattr(self, f"{GEOMETRY_PREFIX}{name}") for name in GEOMETRY_FIELDS
        }
        return ShadingGeometrySettings(**values)

    @property
    def member_glass(self) -> tuple[MemberGlass, ...]:
        """Return the glass that applies to every member, in their order.

        A member's own measurements, else those of the window: this is what
        the geometry computes with (``ShadedElement(config.geometry,
        config.member_glass)``).
        """
        window = self.geometry
        return tuple(
            member_glass_for(window, member.member_id, member.measurements)
            for member in self.members
        )

    @property
    def frost(self) -> FrostSettings:
        """Return the settings of frost protection as one value."""
        return FrostSettings(
            source=self.frost_source,
            threshold=self.frost_threshold,
            hysteresis=self.frost_hysteresis,
            position=self.frost_position,
            applies_to_protection=self.frost_applies_to_protection,
            hold_closed=self.frost_hold_closed,
        )

    @property
    def motor_protection(self) -> MotorProtectionSettings:
        """Return the settings of motor protection as one value."""
        return MotorProtectionSettings(
            min_change=self.motor_min_change, min_interval=self.motor_min_interval
        )

    @property
    def capabilities(self) -> WindowCapabilities:
        """Return the lowest common denominator of the members' capability flags.

        A ``False`` can mean "missing" or "unknown"; whoever decides anything
        from it must read :attr:`capability_states` instead.
        """
        profiles = [member.capabilities for member in self.members]
        return WindowCapabilities(
            supports_open_close=all(p.supports_open_close for p in profiles),
            supports_set_position=all(p.supports_set_position for p in profiles),
            supports_stop=all(p.supports_stop for p in profiles),
            reports_position=all(p.reports_position for p in profiles),
        )

    @property
    def capability_states(self) -> WindowCapabilityStates:
        """Return the capabilities in three states; "missing" takes precedence."""

        def over_members(name: str) -> CapabilityState:
            states = {
                member.capabilities.capability_state(name) for member in self.members
            }
            for state in (CapabilityState.MISSING, CapabilityState.UNKNOWN):
                if state in states:
                    return state
            return CapabilityState.PRESENT

        return WindowCapabilityStates(
            supports_open_close=over_members("supports_open_close"),
            supports_set_position=over_members("supports_set_position"),
            supports_stop=over_members("supports_stop"),
            reports_position=over_members("reports_position"),
        )
