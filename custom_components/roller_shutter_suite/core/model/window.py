"""Window configuration as the core sees it: members and their capabilities."""

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum, unique
from typing import Final

from ._validation import (
    require_finite,
    require_identifier,
    require_type,
    require_unique,
)

MIN_TOLERANCE: Final = 1
DEFAULT_TOLERANCE_CALCULATED: Final = 2
DEFAULT_TOLERANCE_MEASURED: Final = 3
_MAX_TOLERANCE: Final = 100


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

    ``UNKNOWN`` is not ``MISSING``: nobody could be asked, so nothing may be
    concluded from it.
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

    ``capabilities_known`` is ``False`` while the member could not be asked
    what it can do, for example because its entity is not available. All four
    capability flags come from the same report of the member, so they are
    known or unknown together. They then hold the last known state, and the
    member is operated with it; but a flag that is off says nothing definite,
    see :meth:`capability_state`.
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

        While the capabilities are not known, every flag is ``UNKNOWN``,
        whatever the last known state says.
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

    These are the flags the window is operated with. They do not say whether
    they are confirmed; :class:`WindowCapabilityStates` does.
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


@unique
class ScheduleProfile(StrEnum):
    """The key under which the schedule looks up its targets.

    It has one value. The key exists so that an absence profile or named
    profiles can be added without restructuring.
    """

    DEFAULT = "default"


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


@dataclass(frozen=True, slots=True)
class MemberConfig:
    """One cover of a window as the core sees it."""

    member_id: str
    capabilities: CapabilityProfile

    def __post_init__(self) -> None:
        """Validate the member identifier."""
        require_identifier(self.member_id, "the identifier of a member")
        require_type(
            self.capabilities, CapabilityProfile, "the capability profile of a member"
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
    """

    window_id: str
    members: tuple[MemberConfig, ...]
    covering_type: CoveringType = CoveringType.ROLLER_SHUTTER
    morning_condition_source: str | None = None
    shading_temperature_tiers: tuple[TemperatureTier, ...] = ()
    schedule_profile: ScheduleProfile = ScheduleProfile.DEFAULT

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

    @property
    def capabilities(self) -> WindowCapabilities:
        """Return the lowest common denominator of the members' capabilities."""
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
