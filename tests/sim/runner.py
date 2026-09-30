"""The scenario runner: drives the engine the way the runtime will.

The runtime recomputes a window when something it looks at changes, and at
the instants the core names: a report of a member, a change of a source, a
planned action of the schedule, the end of a deferral, the end of an
expectation window. The runner does exactly that, and nothing on a fixed
grid: time jumps from one due instant to the next, which is what makes a
year run in seconds.

Every report of a member goes to the movement tracker of the core
(``Engine.observe``) with the decision of the last recompute; the core drops
a report that changes nothing, and what it raised is recorded.

One recompute, as the runtime performs it:

1. build the world snapshot: the time of the clock, the sun position, every
   source, the members as last observed, the persisted state, the controls,
   the almanac (built once per local date) and the seed;
2. ``engine.elapse`` judges the settle times and deadlines that have passed
   and ends or turns the dams whose time has come;
3. ``engine.recompute`` gives the decision;
4. the state after the decision: what the schedule remembers, what a dry-run
   or a take-over leaves behind, and, if the gate said "send", the commands
   handed to the actuator and written down (``Engine.after_send``);
5. the state is persisted if it changed;
6. the next wake-ups are planned from the decision, the schedule and
   ``Engine.wake_ups``, the one source of every other instant: the runner
   computes no time of its own.

A **restart** throws the engines away, reads every window state back from
the storage and continues; the covers keep their state, as real covers do.
Injected events (a movement by hand, a stop, a dropout, changed controls, a
scripted second controller) are actions the scenario schedules at instants.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta

from custom_components.roller_shutter_suite.core.arbiter import (
    ConstraintRegistration,
    LayerRegistration,
)
from custom_components.roller_shutter_suite.core.engine import Engine, build_arbiter
from custom_components.roller_shutter_suite.core.model import (
    Controls,
    Decision,
    FunctionId,
    GateKind,
    MemberObservation,
    Observation,
    SunAlmanac,
    TrackerEvent,
    Transition,
    WindowConfig,
    WindowObservation,
    WindowState,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.schedule import (
    ScheduleInputMissingError,
    ScheduleResult,
    build_sun_almanac,
    evaluate_schedule,
)

from .record import Entry, EntryKind, Record, decision_summary
from .world import World

type Action = Callable[["Simulation"], None]


@dataclass(frozen=True, slots=True)
class _Injected:
    """An action the scenario scheduled at an instant."""

    at: datetime
    order: int
    label: str
    action: Action


class SimWindow:
    """One window of the simulation: its configuration, controls, state and engine."""

    def __init__(
        self, config: WindowConfig, controls: Controls, engine: Engine
    ) -> None:
        """Start with a fresh state; the runner loads the persisted one."""
        self.config = config
        self.controls = controls
        self.engine = engine
        self.state = WindowState()
        self.observations: dict[str, Observation] = {}
        self.wake_ups: set[datetime] = set()
        self.last_decision: Decision | None = None
        """The decision of the last recompute; the tracker judges by it."""
        self._almanac: tuple[date, SunAlmanac] | None = None

    @property
    def window_id(self) -> str:
        """Return the identifier of the window."""
        return self.config.window_id

    @property
    def member_ids(self) -> tuple[str, ...]:
        """Return the members of the window, in order."""
        return tuple(member.member_id for member in self.config.members)

    def almanac(self, at: datetime, world: World) -> SunAlmanac:
        """Return the almanac for the local date of ``at``, built once per date."""
        if self._almanac is None or self._almanac[0] != at.date():
            self._almanac = (at.date(), build_sun_almanac(self.config, at, world.sun))
        return self._almanac[1]

    def observation(self) -> WindowObservation:
        """Return the members as last observed."""
        return WindowObservation(
            tuple(
                MemberObservation(member_id, self.observations[member_id])
                for member_id in self.member_ids
            )
        )

    def next_wake_up(self) -> datetime | None:
        """Return the earliest planned wake-up, or ``None``."""
        return min(self.wake_ups, default=None)


class Simulation:
    """A scenario: a world, its windows, and the run over them."""

    def __init__(
        self,
        world: World,
        *,
        layers: Iterable[LayerRegistration] | None = None,
        constraints: Iterable[ConstraintRegistration] = (),
    ) -> None:
        """Start with a world and what the arbiter of every window gets.

        Without ``layers`` the arbiter has the layers of the integration
        (``build_arbiter()``): the real fire, protection and schedule layers.
        ``constraints`` are added to the built-in ones; the scenarios of block
        C07 hand in the stand-in for lockout protection of block C08 there.
        """
        self.world = world
        self.record = Record(world.clock.zone)
        self._layers = None if layers is None else tuple(layers)
        self._constraints = tuple(constraints)
        self._windows: dict[str, SimWindow] = {}
        self._injected: list[_Injected] = []
        self._injected_count = 0
        self.recomputes = 0
        self.restarts = 0

    # --- Building the scenario -------------------------------------------------------

    @property
    def now(self) -> datetime:
        """Return the simulated time."""
        return self.world.clock.now()

    @property
    def windows(self) -> Sequence[SimWindow]:
        """Return the windows in the order they were added."""
        return tuple(self._windows.values())

    def window(self, window_id: str) -> SimWindow:
        """Return one window."""
        return self._windows[window_id]

    def add_window(self, config: WindowConfig, controls: Controls) -> SimWindow:
        """Add a window over covers of the world; its state is loaded from the storage."""
        if config.window_id in self._windows:
            raise ValueError(f"a window {config.window_id!r} exists already")
        for member in config.members:
            if member.member_id not in self.world.covers:
                raise ValueError(f"no cover for the member {member.member_id!r}")
        window = SimWindow(config, controls, self._engine(config))
        self._load(window)
        self._windows[config.window_id] = window
        return window

    def at(self, moment: datetime, label: str, action: Action) -> None:
        """Schedule an action at an instant; actions at one instant run in order."""
        self._injected_count += 1
        self._injected.append(
            _Injected(moment.astimezone(UTC), self._injected_count, label, action)
        )
        self._injected.sort(key=lambda entry: (entry.at, entry.order))

    # --- Injected events --------------------------------------------------------------

    def set_controls(self, window_id: str, controls: Controls) -> None:
        """Change what a person set for a window; the window is recomputed."""
        window = self._windows[window_id]
        was_dry_run = window.controls.dry_run
        window.controls = controls
        if was_dry_run and not controls.dry_run:
            window.state = window.engine.arm(window.state)
            self._persist(window)
        self._note(
            EntryKind.EVENT,
            f"controls changed: {_controls_text(controls)}",
            window_id=window_id,
        )
        self._recompute(window)

    def move_by_hand(
        self,
        window_id: str,
        target: int,
        *,
        member_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """Move a window, or one of its members, by hand at its own control.

        ``user_id`` stands for a movement from a dashboard: the first reports
        carry the user in their context, as Home Assistant's do.
        """
        window = self._windows[window_id]
        members = window.member_ids if member_id is None else (member_id,)
        for member in members:
            self.world.cover(member).move_to(
                target, self.now, by="user", user_id=user_id
            )
            self._note(
                EntryKind.EVENT,
                f"moved by hand to {target}",
                window_id=window_id,
                member_id=member,
                foreign=True,
            )

    def resume(self, window_id: str) -> None:
        """Press "resume automation" for a window: the manual override ends."""
        window = self._windows[window_id]
        self._note(EntryKind.EVENT, "resume automation", window_id=window_id)
        self._apply(window, window.engine.resume(window.state))
        self._recompute(window)

    def acknowledge_fire(self, window_id: str) -> None:
        """Acknowledge the fire alarm for a window (the action and the button)."""
        window = self._windows[window_id]
        self._note(EntryKind.EVENT, "fire alarm acknowledged", window_id=window_id)
        self._apply(window, window.engine.acknowledge_fire(window.state))
        self._recompute(window)

    def sleep_mode_switched_on(self, window_id: str) -> None:
        """Switch sleep mode on for a window: the manual override ends."""
        window = self._windows[window_id]
        self._note(EntryKind.EVENT, "sleep mode switched on", window_id=window_id)
        self._apply(window, window.engine.sleep_mode_switched_on(window.state))
        self._recompute(window)

    def other_controller_moves(self, window_id: str, target: int) -> None:
        """Let a scripted second controller move the same covers."""
        window = self._windows[window_id]
        for member in window.member_ids:
            self.world.cover(member).move_to(target, self.now, by="other")
            self._note(
                EntryKind.EVENT,
                f"another controller sends {target}",
                window_id=window_id,
                member_id=member,
                foreign=True,
            )

    def stop_by_hand(self, window_id: str, member_id: str) -> None:
        """Stop a member in mid-travel, by hand."""
        self.world.cover(member_id).stop(self.now)
        self._note(
            EntryKind.EVENT,
            "stopped by hand",
            window_id=window_id,
            member_id=member_id,
            foreign=True,
        )

    def dropout(self, window_id: str, member_id: str, duration: timedelta) -> None:
        """Let a member lose its connection for a while; it returns as it is."""
        self.world.cover(member_id).disconnect(self.now, self.now + duration)
        self._note(
            EntryKind.EVENT,
            f"connectivity dropout for {duration}",
            window_id=window_id,
            member_id=member_id,
            foreign=True,
        )

    def restart(self) -> None:
        """Throw the core away, rebuild every window from the storage, continue."""
        self.restarts += 1
        self._note(EntryKind.RESTART, "the core restarts; states come from the storage")
        for window in self._windows.values():
            window.engine = self._engine(window.config)
            window.wake_ups.clear()
            window.last_decision = None
            self._load(window)
            # The entities are read once at start, as the runtime reads them.
            self._read_members(window)
        for window in self._windows.values():
            if window.observation().available:
                self._recompute(window)

    # --- Running ------------------------------------------------------------------------

    def run(self, until: datetime) -> Record:
        """Advance from now to ``until``, instant by instant; return the record."""
        end = until.astimezone(UTC)
        if not self._windows:
            raise ValueError("a simulation runs over at least one window")
        self._start_windows()
        while True:
            due = self._next_due()
            if due is None or due > end:
                break
            previous = self.now.astimezone(UTC)
            self.world.clock.advance_to(due)
            to_recompute: dict[str, SimWindow] = {}
            if self.world.script.next_change_after(previous) == due:
                self._note(EntryKind.SOURCE, "a source changed")
                to_recompute.update(self._windows)
            for window in self._windows.values():
                if self._deliver_reports(window):
                    to_recompute[window.window_id] = window
                if any(wake <= due for wake in window.wake_ups):
                    window.wake_ups = {wake for wake in window.wake_ups if wake > due}
                    to_recompute[window.window_id] = window
            while self._injected and self._injected[0].at <= due:
                injected = self._injected.pop(0)
                self._note(EntryKind.EVENT, f"scenario: {injected.label}")
                injected.action(self)
            for window in to_recompute.values():
                self._recompute(window)
        self.world.clock.advance_to(end)
        return self.record

    def _start_windows(self) -> None:
        """Read the covers once and decide for every window that is available."""
        for window in self._windows.values():
            if not window.observations:
                for member_id in window.member_ids:
                    self.world.cover(member_id).reports_due(self.now)
                self._read_members(window)
                if window.observation().available:
                    self._recompute(window)

    def _read_members(self, window: SimWindow) -> None:
        """Read the state of every member once, and hand it to the tracker.

        What the tracker already knows (after a restart, the persisted last
        observation) changes nothing; a first observation is only recorded.
        """
        for member_id in window.member_ids:
            observation = self.world.cover(member_id).current_observation()
            window.observations[member_id] = observation
            self._apply(
                window,
                window.engine.observe(
                    window.state,
                    member_id,
                    observation,
                    self.now,
                    window.last_decision,
                    dry_run=window.controls.dry_run,
                ),
            )

    def _next_due(self) -> datetime | None:
        now = self.now.astimezone(UTC)
        candidates: list[datetime] = []
        if (change := self.world.script.next_change_after(now)) is not None:
            candidates.append(change)
        for cover in self.world.covers.values():
            if (report := cover.next_report_at()) is not None:
                candidates.append(max(report, now))
        for window in self._windows.values():
            if (wake := window.next_wake_up()) is not None:
                candidates.append(wake)
        if self._injected:
            candidates.append(self._injected[0].at)
        return min(candidates, default=None)

    def _deliver_reports(self, window: SimWindow) -> bool:
        """Hand the reports of the members to the tracker; say whether one changed.

        The core normalizes: a report whose observation changes nothing
        (a repeated write, a rewrite with a new change time) comes back as
        the same state, and the runner counts it as dropped.
        """
        changed = False
        for member_id in window.member_ids:
            cover = self.world.cover(member_id)
            for report in cover.reports_due(self.now):
                observation = report.observation()
                transition = window.engine.observe(
                    window.state,
                    member_id,
                    observation,
                    report.at,
                    window.last_decision,
                    dry_run=window.controls.dry_run,
                    user_id=report.user_id,
                )
                if transition.state is window.state:
                    self.record.dropped_reports += 1
                    continue
                window.observations[member_id] = observation
                changed = True
                position = (
                    "-" if observation.position is None else observation.position.value
                )
                self.record.add(
                    Entry(
                        report.at,
                        EntryKind.REPORT,
                        f"{report.state} at {position}",
                        window_id=window.window_id,
                        member_id=member_id,
                        observation=observation,
                    )
                )
                self._apply(window, transition, at=report.at)
        return changed

    def _apply(
        self, window: SimWindow, transition: Transition, *, at: datetime | None = None
    ) -> None:
        """Take the state of a transition, persist it, and record its events."""
        for event in transition.events:
            self.record.add(
                Entry(
                    self.now if at is None else at,
                    EntryKind.TRACKER,
                    _event_text(event),
                    window_id=window.window_id,
                    member_id=event.member_id,
                    event=event,
                )
            )
        if transition.state is not window.state and transition.state != window.state:
            window.state = transition.state
            self._persist(window)

    # --- One recompute -------------------------------------------------------------------

    def _engine(self, config: WindowConfig) -> Engine:
        return Engine(
            config, build_arbiter(self._layers, constraints=self._constraints)
        )

    def _load(self, window: SimWindow) -> None:
        data = self.world.storage.load_window_state(window.window_id)
        window.state = WindowState() if data is None else WindowState.from_data(data)

    def _persist(self, window: SimWindow) -> None:
        self.world.storage.save_window_state(window.window_id, window.state.to_data())

    def _snapshot(self, window: SimWindow) -> WorldSnapshot:
        now = self.now
        return WorldSnapshot(
            time=now,
            sun=self.world.sun.position(now),
            sources=self.world.script.values_at(now),
            observation=window.observation(),
            state=window.state,
            controls=window.controls,
            almanac=window.almanac(now, self.world),
            installation_seed=self.world.storage.load_seed(),
        )

    def _recompute(self, window: SimWindow) -> Decision:
        self.recomputes += 1
        snapshot = self._snapshot(window)
        self._apply(window, window.engine.elapse(snapshot, window.last_decision))
        snapshot = replace(snapshot, state=window.state)
        decision = window.engine.recompute(snapshot)
        window.last_decision = decision
        state = snapshot.state
        wake_ups: set[datetime] = set()
        schedule = self._schedule(window, snapshot)
        if schedule is not None:
            state = schedule.state
            if schedule.next_action is not None:
                wake_ups.add(schedule.next_action.at)
            if schedule.recheck_at is not None:
                wake_ups.add(schedule.recheck_at)
        snapshot = replace(snapshot, state=state)
        state = window.engine.state_after(snapshot, decision)
        self.record.add(
            Entry(
                self.now,
                EntryKind.DECISION,
                decision_summary(decision),
                window_id=window.window_id,
                target=decision.target,
                wish_class=(
                    None
                    if decision.winning_wish is None
                    else decision.winning_wish.wish_class
                ),
                decision=decision,
            )
        )
        gate = decision.gate
        if gate is not None:
            if gate.kind is GateKind.SEND:
                state = self._send(window, replace(snapshot, state=state), decision)
            if gate.until is not None:
                wake_ups.add(gate.until)
            if gate.reevaluate_no_later_than is not None:
                wake_ups.add(gate.reevaluate_no_later_than)
        if state != window.state:
            window.state = state
            self._persist(window)
        now = self.now
        wake_ups.update(
            window.engine.wake_ups(window.state, now, dry_run=window.controls.dry_run)
        )
        window.wake_ups = {wake.astimezone(UTC) for wake in wake_ups if wake > now}
        return decision

    def _schedule(
        self, window: SimWindow, snapshot: WorldSnapshot
    ) -> ScheduleResult | None:
        """Ask the schedule what it remembers and when it acts next.

        This is one evaluation with the arguments the layer saw during the
        recompute; ``schedule_state_after`` of the core would evaluate the
        same thing and return only its state. The runtime needs the next
        planned action and the recheck time as well, to set its timers.
        """
        config = window.config
        if (
            not config.schedule_enabled
            or FunctionId.SCHEDULE in config.disabled_functions
        ):
            return None
        try:
            return evaluate_schedule(config, snapshot)
        except ScheduleInputMissingError:
            return None

    def _send(
        self, window: SimWindow, snapshot: WorldSnapshot, decision: Decision
    ) -> WindowState:
        if window.controls.dry_run:
            raise AssertionError("the runner never sends for a window in dry-run")
        command_ids: dict[str, str] = {}
        stamp = self.now.astimezone(UTC).isoformat(timespec="milliseconds")
        # The core names the members a send addresses; the runner filters
        # nothing of its own, exactly as the runtime.
        for member_id, position in decision.addressed_targets:
            command_id = f"{window.window_id}/{member_id}/{stamp}"
            self.world.actuator.move_to(command_id, member_id, position)
            command_ids[member_id] = command_id
        sent = window.engine.after_send(snapshot, decision, command_ids)
        state = sent.state
        for event in sent.events:
            self.record.add(
                Entry(
                    self.now,
                    EntryKind.TRACKER,
                    _event_text(event),
                    window_id=window.window_id,
                    event=event,
                )
            )
        recorded = {
            member.member_id: member.last_own_command for member in state.members
        }
        for member_id, position in decision.addressed_targets:
            command = recorded[member_id]
            assert command is not None
            self.record.add(
                Entry(
                    self.now,
                    EntryKind.COMMAND,
                    f"send {position.value} "
                    f"({command.wish_class.value}, {command.reason.value})",
                    window_id=window.window_id,
                    member_id=member_id,
                    target=position,
                    wish_class=command.wish_class,
                )
            )
        return state

    # --- Recording ---------------------------------------------------------------------

    def _note(
        self,
        kind: EntryKind,
        summary: str,
        *,
        window_id: str | None = None,
        member_id: str | None = None,
        foreign: bool = False,
    ) -> None:
        self.record.add(
            Entry(
                self.now,
                kind,
                summary,
                window_id=window_id,
                member_id=member_id,
                foreign=foreign,
            )
        )


def _event_text(event: TrackerEvent) -> str:
    """Return one readable line for an event of the tracker or the dams."""
    parts = [event.code.value]
    if event.event_id is not None:
        parts.append(f"[{event.event_id}]")
    if event.source is not None:
        parts.append(f"(source {event.source})")
    if event.position is not None:
        parts.append(f"at {event.position.value}")
    if event.count is not None:
        parts.append(f"count {event.count} of {event.threshold}")
    if event.user_id is not None:
        parts.append(f"(user {event.user_id})")
    return " ".join(parts)


def _controls_text(controls: Controls) -> str:
    parts = [f"dry_run={controls.dry_run}"]
    for name, level in zip(("global", "group", "window"), controls.levels, strict=True):
        if level.paused or level.maintenance_lock or level.mode.value != "automatic":
            parts.append(
                f"{name}: paused={level.paused} lock={level.maintenance_lock} mode={level.mode.value}"
            )
    return ", ".join(parts)
