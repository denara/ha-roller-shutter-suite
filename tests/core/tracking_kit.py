"""What the tests of the movement tracker and the dams share.

A window of one or two members, the engine with the stub layers of the
arbiter kit, observations by their meaning, and a little driver that walks a
state through observations and elapsed time the way the runtime does:
``observe`` for every report, ``elapse`` before every recompute.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from custom_components.roller_shutter_suite.core.engine import Engine, build_arbiter
from custom_components.roller_shutter_suite.core.model import (
    Decision,
    MemberObservation,
    MovementState,
    Observation,
    Position,
    TrackerEvent,
    Transition,
    WindowConfig,
    WindowObservation,
    WindowState,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import (
    ARMED,
    DRY_RUN,
    LEFT,
    NOW,
    STUB_LAYERS,
    day,
    snapshot,
    window,
)


def resting(position: int | None) -> Observation:
    """Return a member at rest, at a position or reporting none."""
    return Observation(
        MovementState.RESTING, None if position is None else Position(position)
    )


def moving_up(position: int) -> Observation:
    """Return a member that reports "opening" at a position."""
    return Observation(MovementState.MOVING_UP, Position(position))


def moving_down(position: int) -> Observation:
    """Return a member that reports "closing" at a position."""
    return Observation(MovementState.MOVING_DOWN, Position(position))


UNAVAILABLE = Observation(MovementState.UNAVAILABLE)


def codes(events: Iterable[TrackerEvent]) -> list[ReasonCode]:
    """Return the codes of events, in order."""
    return [event.code for event in events]


@dataclass
class Driver:
    """A window whose state is walked through reports and time, as the runtime does.

    ``observed`` is the last observation of every member (for the snapshot of
    a recompute); ``events`` collects every event raised so far.
    """

    config: WindowConfig
    state: WindowState = field(default_factory=WindowState)
    now: datetime = NOW
    dry_run: bool = False
    last_decision: Decision | None = None
    sources: dict[str, Any] = field(default_factory=day)
    observed: dict[str, Observation] = field(default_factory=dict)
    events: list[TrackerEvent] = field(default_factory=list)

    @property
    def engine(self) -> Engine:
        """Return the engine of the window, with the stub layers."""
        return Engine(self.config, build_arbiter(STUB_LAYERS))

    def at(self, seconds: float) -> Driver:
        """Move the time to ``seconds`` after ``NOW``."""
        self.now = NOW + timedelta(seconds=seconds)
        return self

    def _take(self, transition: Transition) -> tuple[TrackerEvent, ...]:
        self.state = transition.state
        self.events.extend(transition.events)
        return transition.events

    def report(
        self,
        observation: Observation,
        member: str = LEFT,
        *,
        user_id: str | None = None,
    ) -> tuple[TrackerEvent, ...]:
        """Hand one report of a member to the tracker; return what it raised."""
        self.observed[member] = observation
        return self._take(
            self.engine.observe(
                self.state,
                member,
                observation,
                self.now,
                self.last_decision,
                dry_run=self.dry_run,
                user_id=user_id,
            )
        )

    def snapshot(self) -> WorldSnapshot:
        """Return the snapshot of a recompute now."""
        members = tuple(
            MemberObservation(
                member.member_id,
                self.observed.get(member.member_id, UNAVAILABLE),
            )
            for member in self.config.members
        )
        world = snapshot(
            sources=self.sources,
            observation=WindowObservation(members),
            state=self.state,
            controls=DRY_RUN if self.dry_run else ARMED,
        )
        return replace(world, time=self.now)

    def elapse(self) -> tuple[TrackerEvent, ...]:
        """Let the time come to ``now``: settle times, deadlines, the dams."""
        return self._take(self.engine.elapse(self.snapshot(), self.last_decision))

    def recompute(self) -> Decision:
        """Elapse, decide, and record a send the way the runtime does."""
        self.elapse()
        world = self.snapshot()
        decision = self.engine.recompute(world)
        self.last_decision = decision
        state = self.engine.state_after(world, decision)
        ids = {
            member: f"command-{member}-{self.now.isoformat()}"
            for member, _ in decision.addressed_targets
        }
        sent = self.engine.after_send(replace(world, state=state), decision, ids)
        self._take(sent)
        return decision


def driver(*member_ids: str, **changes: Any) -> Driver:
    """Return a driver over a window of the given members (one by default)."""
    config = window(*member_ids, **changes) if member_ids else window(**changes)
    return Driver(config)
