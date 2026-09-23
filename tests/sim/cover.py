"""The simulated cover behind the actuator port, with a behaviour profile.

A :class:`SimulatedCover` is a motor with a curtain and an actuator that
reports about it. Its :class:`CoverProfile` says how it travels and how it
reports, following the measured facts of section 8 of the architecture and
the taxonomy of pitfalls in the brief's section 7:

- travel time per direction, and not linear in percent: a movement that ends
  in an end stop takes ``end_stop_extra`` longer;
- reports transit states (``opening``/``closing``) or not;
- reports positions live during the travel, only at the end (the old position
  is kept during the travel and jumps to the target), or only on a fixed grid
  of about a minute with no transit state and no report at the real end of the
  movement (a polled platform);
- the start report already carries a position a few percent into the travel;
- settles exactly or a few percent off, also asymmetric per direction;
- supports stop or not; reports a position or not;
- delivers its last report late (``report_delay``);
- writes the position shortly before the resting state, repeats its last
  write after a few milliseconds, rewrites an unchanged state with a new
  change time while idle;
- **a calculated position that reports the commanded target although the
  curtain was blocked**: the actuator counts run time and the motor cut out at
  ``blocked_at``. The real position is kept separately, so a scenario can
  show the drift between what is reported and where the curtain is.

The cover produces **raw reports**, what a cover entity would write: a state
(``open``, ``closed``, ``opening``, ``closing``, ``unavailable``), a position
or none, and the instant of the write. The runner normalizes them to
observations of the core and drops a report that changes nothing, as the
tracker of the runtime will (section 8.2). Reports are generated when a
command arrives, as a schedule of writes, and delivered when the runner asks
for them; a connectivity dropout swallows the writes of its gap and lets the
cover return with the state it has then.

Everything is deterministic: the same commands at the same instants yield the
same reports. A profile that wants noise takes it from the seeded random
generator of the world when the scenario is built, not from here.
"""

import math
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum, unique
from typing import Final

from custom_components.roller_shutter_suite.core.model import (
    CapabilityProfile,
    MovementState,
    Observation,
    Position,
    PositionSource,
    PositionUpdates,
    TransitReporting,
)

FULL_TRAVEL: Final = 100
_HALFWAY: Final = 50
_ATTRIBUTE_WRITE_BEFORE_REST: Final = timedelta(milliseconds=20)
_REPEATED_WRITE_AFTER: Final = timedelta(milliseconds=10)


@unique
class Reporting(StrEnum):
    """When a cover reports its position during a movement."""

    LIVE = "live"
    """Every ``live_interval`` during the travel, with a transit state."""
    END_ONLY = "end_only"
    """The old position during the travel, the target at the end."""
    GRID = "grid"
    """Only on a fixed grid, no transit state, no report at the real end."""


@dataclass(frozen=True, slots=True)
class CoverProfile:
    """How a simulated cover travels and reports; see the module documentation."""

    name: str
    travel_time_up: timedelta = timedelta(seconds=20)
    travel_time_down: timedelta = timedelta(seconds=18)
    end_stop_extra: timedelta = timedelta(0)
    supports_set_position: bool = True
    supports_stop: bool = True
    reports_position: bool = True
    position_source: PositionSource = PositionSource.CALCULATED
    transit_states: bool = True
    reporting: Reporting = Reporting.LIVE
    live_interval: timedelta = timedelta(seconds=2)
    grid_interval: timedelta = timedelta(seconds=60)
    start_latency: timedelta = timedelta(milliseconds=700)
    start_offset_percent: int = 0
    settle_offset_up: int = 0
    settle_offset_down: int = 0
    report_delay: timedelta = timedelta(0)
    position_before_rest: bool = False
    repeat_last_write: bool = False
    rewrite_unchanged_every: timedelta | None = None
    blocked_at: int | None = None

    def __post_init__(self) -> None:
        """Validate the durations and percentages."""
        for name in ("travel_time_up", "travel_time_down"):
            if getattr(self, name) <= timedelta(0):
                raise ValueError(f"{name} must be longer than zero")
        for name in ("live_interval", "grid_interval"):
            if getattr(self, name) <= timedelta(0):
                raise ValueError(f"{name} must be longer than zero")
        for name in ("end_stop_extra", "start_latency", "report_delay"):
            if getattr(self, name) < timedelta(0):
                raise ValueError(f"{name} must not be negative")
        if not 0 <= self.start_offset_percent <= FULL_TRAVEL:
            raise ValueError("the start offset is a percentage")
        if self.blocked_at is not None and not 0 <= self.blocked_at <= FULL_TRAVEL:
            raise ValueError("the blocked position is a percentage")
        if self.rewrite_unchanged_every is not None and (
            self.rewrite_unchanged_every <= timedelta(0)
        ):
            raise ValueError("the rewrite interval must be longer than zero")

    @property
    def report_delay_for_the_core(self) -> timedelta:
        """Return the report delay the capability profile states.

        A polled platform lags by up to one grid interval; the user states
        that as the report delay, plus what the platform itself delays.
        """
        if self.reporting is Reporting.GRID:
            return self.report_delay + self.grid_interval
        return self.report_delay

    def capability_profile(self) -> CapabilityProfile:
        """Return what the user would state about this cover."""
        return CapabilityProfile(
            supports_open_close=True,
            supports_set_position=self.supports_set_position,
            supports_stop=self.supports_stop,
            reports_position=self.reports_position,
            travel_time_up=self.travel_time_up,
            travel_time_down=self.travel_time_down,
            position_source=self.position_source,
            reports_transit_states=(
                TransitReporting.YES if self.transit_states else TransitReporting.NO
            ),
            position_updates=(
                PositionUpdates.LIVE
                if self.reporting is Reporting.LIVE
                else PositionUpdates.END_ONLY
            ),
            report_delay=self.report_delay_for_the_core,
        )


@dataclass(frozen=True, slots=True)
class RawReport:
    """One state write of a cover entity, as the runtime would receive it."""

    at: datetime
    state: str
    position: int | None = None

    def __post_init__(self) -> None:
        """Keep the instant in UTC."""
        if self.at.tzinfo is None or self.at.utcoffset() is None:
            raise ValueError("a report is written at a timezone-aware instant")
        object.__setattr__(self, "at", self.at.astimezone(UTC))

    def observation(self) -> Observation:
        """Return the observation of the core for this report."""
        if self.state == "unavailable":
            return Observation(MovementState.UNAVAILABLE)
        state = {
            "opening": MovementState.MOVING_UP,
            "closing": MovementState.MOVING_DOWN,
        }.get(self.state, MovementState.RESTING)
        position = None if self.position is None else Position(self.position)
        return Observation(state, position)


def _clamp(value: float) -> int:
    return max(0, min(FULL_TRAVEL, round(value)))


@dataclass(frozen=True, slots=True)
class _Motion:
    """A movement under way: where it started, where it goes, how long it takes.

    ``real_from`` is where the curtain really was, ``reported_from`` what the
    actuator counted. ``real_end`` is where the curtain really ends: the
    target, plus a settle offset, unless the motor cut out at ``blocked_at``.
    ``reported_end`` is what the actuator reports at the end: with a
    calculated position the target, with a measured one the real end.
    """

    started_at: datetime
    duration: timedelta
    real_from: float
    reported_from: float
    target: int
    real_end: float
    reported_end: int
    up: bool

    @property
    def ends_at(self) -> datetime:
        """Return when the actuator stops counting."""
        return self.started_at + self.duration

    def share(self, at: datetime) -> float:
        """Return how much of the movement is done at an instant, 0 to 1."""
        if self.duration <= timedelta(0):
            return 1.0
        done = (at - self.started_at) / self.duration
        return max(0.0, min(1.0, done))

    def reported_at(self, at: datetime) -> float:
        """Return what the actuator counts at an instant."""
        share = self.share(at)
        if share >= 1.0:
            return float(self.reported_end)
        return self.reported_from + (self.target - self.reported_from) * share

    def real_at(self, at: datetime) -> float:
        """Return where the curtain really is at an instant.

        The curtain follows the count until it arrives, or until it reaches
        the place where the motor cut out (``real_end`` short of the target);
        a settle offset beyond the target appears at the end.
        """
        share = self.share(at)
        if share >= 1.0:
            return self.real_end
        counted = self.real_from + (self.target - self.real_from) * share
        if self.up and self.real_end < self.target:
            return min(counted, self.real_end)
        if not self.up and self.real_end > self.target:
            return max(counted, self.real_end)
        return counted


class SimulatedCover:
    """One cover: a curtain, a motor, and the actuator that reports about them."""

    def __init__(
        self,
        cover_id: str,
        profile: CoverProfile,
        *,
        position: int = FULL_TRAVEL,
        available_since: datetime | None = None,
    ) -> None:
        """Start at rest at ``position``; report it once at ``available_since``."""
        self.cover_id = cover_id
        self.profile = profile
        self._real: float = float(position)
        self._reported: float = float(position)
        self._motion: _Motion | None = None
        self._pending: list[RawReport] = []
        self._gap: tuple[datetime, datetime] | None = None
        self.last_report: RawReport | None = None
        self.commands: list[tuple[datetime, int, str]] = []
        """Every command that reached the motor: when, the target, who sent it."""
        if available_since is not None:
            self._pending.append(self._resting_report(available_since))

    # --- What the world sees --------------------------------------------------------

    def real_position(self, at: datetime) -> float:
        """Return where the curtain really is."""
        if self._motion is not None:
            return self._motion.real_at(at)
        return self._real

    def reported_position(self, at: datetime) -> float:
        """Return what the actuator counts, whether or not it has been reported."""
        if self._motion is not None:
            return self._motion.reported_at(at)
        return self._reported

    def moving(self, at: datetime) -> bool:
        """Return whether the motor runs at an instant."""
        return self._motion is not None and at < self._motion.ends_at

    def current_observation(self) -> Observation:
        """Return the observation of the last delivered report; unavailable if none."""
        if self.last_report is None:
            return Observation(MovementState.UNAVAILABLE)
        return self.last_report.observation()

    # --- Commands and events ------------------------------------------------------------

    def move_to(self, target: int, at: datetime, by: str = "engine") -> None:
        """Command the motor to a position; a running movement is reversed or retargeted.

        A cover without "set position" only knows open and close: a target
        from 50 upwards opens, a lower one closes. A target equal to the
        counted position does nothing and writes nothing.
        """
        if not 0 <= target <= FULL_TRAVEL:
            raise ValueError("a target is a percentage")
        if not self.profile.supports_set_position:
            target = FULL_TRAVEL if target >= _HALFWAY else 0
        at = at.astimezone(UTC)
        self._settle_motion(at)
        self.commands.append((at, target, by))
        reported_from = self.reported_position(at)
        real_from = self.real_position(at)
        if round(reported_from) == target and self._motion is None:
            return
        self._drop_motion_reports()
        up = target > reported_from
        travel = self.profile.travel_time_up if up else self.profile.travel_time_down
        share = abs(target - reported_from) / FULL_TRAVEL
        duration = travel * share
        if target in (0, FULL_TRAVEL):
            duration += self.profile.end_stop_extra
        offset = (
            self.profile.settle_offset_up if up else self.profile.settle_offset_down
        )
        real_end = float(_clamp(target + offset))
        blocked = self.profile.blocked_at
        if blocked is not None and (
            (up and real_from < blocked < target)
            or (not up and target < blocked < real_from)
        ):
            real_end = float(blocked)
        reported_end = (
            target
            if self.profile.position_source is PositionSource.CALCULATED
            else _clamp(real_end)
        )
        self._motion = _Motion(
            started_at=at,
            duration=duration,
            real_from=real_from,
            reported_from=reported_from,
            target=target,
            real_end=real_end,
            reported_end=reported_end,
            up=up,
        )
        self._schedule_reports(self._motion)

    def stop(self, at: datetime) -> None:
        """Stop the motor where it is; a cover without stop ignores it."""
        if not self.profile.supports_stop:
            return
        at = at.astimezone(UTC)
        motion = self._motion
        if motion is None or at >= motion.ends_at:
            self._settle_motion(at)
            return
        self._real = motion.real_at(at)
        self._reported = motion.reported_at(at)
        self._motion = None
        self._drop_motion_reports()
        if self.profile.reporting is Reporting.GRID:
            self._pending.append(self._resting_report(self._next_grid_tick(at)))
        else:
            self._pending.append(
                self._resting_report(
                    at + self.profile.start_latency + self.profile.report_delay
                )
            )

    def disconnect(self, at: datetime, until: datetime) -> None:
        """Become unavailable for a while; return with the state of that moment."""
        at = at.astimezone(UTC)
        until = until.astimezone(UTC)
        if until <= at:
            raise ValueError("a dropout ends after it began")
        self._gap = (at, until)
        self._pending.append(RawReport(at, "unavailable"))

    # --- Delivering reports ----------------------------------------------------------

    def next_report_at(self) -> datetime | None:
        """Return when the next write is due, or ``None`` if none is scheduled."""
        due = [report.at for report in self._pending]
        if self._gap is not None:
            due.append(self._gap[1])
        if (rewrite := self._next_rewrite()) is not None:
            due.append(rewrite)
        return min(due, default=None)

    def reports_due(self, until: datetime) -> list[RawReport]:
        """Deliver every write due up to an instant, in order; swallow the gap."""
        until = until.astimezone(UTC)
        delivered: list[RawReport] = []
        while True:
            self._pending.sort(key=lambda report: report.at)
            candidates = [r.at for r in self._pending[:1]]
            if self._gap is not None:
                candidates.append(self._gap[1])
            if (rewrite := self._next_rewrite()) is not None:
                candidates.append(rewrite)
            if not candidates or min(candidates) > until:
                break
            nearest = min(candidates)
            if self._gap is not None and nearest == self._gap[1]:
                # The cover returns with the state it has at that moment.
                self._gap = None
                report = self._state_report(nearest)
            elif self._pending and self._pending[0].at == nearest:
                report = self._pending.pop(0)
                if self._gap is not None and self._gap[0] < report.at < self._gap[1]:
                    # A write during the dropout never reaches the runtime.
                    self._settle_motion(report.at)
                    continue
            else:
                # An unchanged state rewritten with a new change time.
                assert self.last_report is not None
                report = replace(self.last_report, at=nearest)
            self._settle_motion(report.at)
            self.last_report = report
            delivered.append(report)
        return delivered

    # --- Internals ---------------------------------------------------------------------

    def _settle_motion(self, at: datetime) -> None:
        motion = self._motion
        if motion is not None and at >= motion.ends_at:
            self._real = motion.real_end
            self._reported = float(motion.reported_end)
            self._motion = None

    def _drop_motion_reports(self) -> None:
        self._pending = [r for r in self._pending if r.state == "unavailable"]

    def _resting_state(self, position: float) -> str:
        return "closed" if _clamp(position) == 0 else "open"

    def _position_or_none(self, position: float) -> int | None:
        return _clamp(position) if self.profile.reports_position else None

    def _resting_report(self, at: datetime) -> RawReport:
        reported = self.reported_position(at)
        return RawReport(
            at, self._resting_state(reported), self._position_or_none(reported)
        )

    def _state_report(self, at: datetime) -> RawReport:
        """Return what the cover would write at an instant, moving or not."""
        motion = self._motion
        if motion is not None and at < motion.ends_at and self.profile.transit_states:
            return RawReport(
                at,
                "opening" if motion.up else "closing",
                self._position_or_none(self._reported_for_report(motion, at)),
            )
        return self._resting_report(at)

    def _reported_for_report(self, motion: _Motion, at: datetime) -> float:
        """Return the position a report carries: live, or the old one."""
        if self.profile.reporting is Reporting.END_ONLY:
            return motion.reported_from
        return motion.reported_at(at)

    def _next_grid_tick(self, at: datetime) -> datetime:
        grid = self.profile.grid_interval
        elapsed = at - datetime(1970, 1, 1, tzinfo=UTC)
        ticks = math.floor(elapsed / grid) + 1
        return datetime(1970, 1, 1, tzinfo=UTC) + grid * ticks

    def _next_rewrite(self) -> datetime | None:
        every = self.profile.rewrite_unchanged_every
        if every is None or self.last_report is None or self._motion is not None:
            return None
        if self.last_report.state == "unavailable":
            return None
        return self.last_report.at + every

    def _schedule_reports(self, motion: _Motion) -> None:
        profile = self.profile
        transit = "opening" if motion.up else "closing"
        end_at = motion.ends_at + profile.report_delay
        if profile.reporting is Reporting.GRID:
            tick = self._next_grid_tick(motion.started_at)
            while tick < end_at:
                counted = motion.reported_at(tick)
                self._pending.append(
                    RawReport(
                        tick,
                        self._resting_state(counted),
                        self._position_or_none(counted),
                    )
                )
                tick += profile.grid_interval
            self._pending.append(
                RawReport(
                    tick,
                    self._resting_state(motion.reported_end),
                    self._position_or_none(motion.reported_end),
                )
            )
            return
        first = motion.started_at + profile.start_latency
        if first < motion.ends_at:
            start_position = self._reported_for_report(motion, first)
            if profile.reporting is Reporting.LIVE and profile.start_offset_percent:
                step = profile.start_offset_percent
                low, high = sorted((motion.reported_from, float(motion.target)))
                start_position += step if motion.up else -step
                start_position = max(low, min(high, start_position))
            state = (
                transit
                if profile.transit_states
                else self._resting_state(start_position)
            )
            self._pending.append(
                RawReport(first, state, self._position_or_none(start_position))
            )
            if profile.reporting is Reporting.LIVE:
                tick = first + profile.live_interval
                while tick < motion.ends_at:
                    counted = motion.reported_at(tick)
                    state = (
                        transit
                        if profile.transit_states
                        else self._resting_state(counted)
                    )
                    self._pending.append(
                        RawReport(tick, state, self._position_or_none(counted))
                    )
                    tick += profile.live_interval
        final_state = self._resting_state(motion.reported_end)
        final_position = self._position_or_none(motion.reported_end)
        if profile.position_before_rest and profile.transit_states:
            self._pending.append(
                RawReport(
                    end_at - _ATTRIBUTE_WRITE_BEFORE_REST, transit, final_position
                )
            )
        self._pending.append(RawReport(end_at, final_state, final_position))
        if profile.repeat_last_write:
            self._pending.append(
                RawReport(end_at + _REPEATED_WRITE_AFTER, final_state, final_position)
            )
