"""The scenario runner: drives the engine the way the runtime will.

The runtime recomputes a window when something it looks at changes, and at
the instants the core names: a report of a member, a change of a source, a
planned action of the schedule, the end of a deferral, the end of an
expectation window. The runner does exactly that, and nothing on a fixed
grid: time jumps from one due instant to the next, which is what makes a
year run in seconds.

One recompute, as the runtime performs it:

1. build the world snapshot: the time of the clock, the sun position, every
   source, the members as last observed, the persisted state, the controls,
   the almanac (built once per local date) and the seed;
2. ``engine.recompute`` gives the decision;
3. the state after the decision: what the schedule remembers, what a dry-run
   or a take-over leaves behind, and, if the gate said "send", the commands
   handed to the actuator and written down (``Engine.state_after_send``);
4. the state is persisted if it changed;
5. the next wake-ups are planned from the decision and the schedule.

A **restart** throws the engines away, reads every window state back from
the storage and continues; the covers keep their state, as real covers do.
Injected events (a movement by hand, a stop, a dropout, changed controls, a
scripted second controller) are actions the scenario schedules at instants.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta

from custom_components.roller_shutter_suite.core.arbiter import (
    LayerRegistration,
    member_expectation_end,
)
from custom_components.roller_shutter_suite.core.engine import Engine, build_arbiter
from custom_components.roller_shutter_suite.core.model import (
    Controls,
    Decision,
    FunctionId,
    GateKind,
    MemberObservation,
    Observation,
    OwnCommand,
    SunAlmanac,
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
from .stubs import DEFAULT_LAYERS
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
        layers: Iterable[LayerRegistration] = DEFAULT_LAYERS,
    ) -> None:
        """Start with a world and the layers the arbiter of every window gets."""
        self.world = world
        self.record = Record(world.clock.zone)
        self._layers = tuple(layers)
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
        self, window_id: str, target: int, *, member_id: str | None = None
    ) -> None:
        """Move a window, or one of its members, by hand at its own control."""
        window = self._windows[window_id]
        members = window.member_ids if member_id is None else (member_id,)
        for member in members:
            self.world.cover(member).move_to(target, self.now, by="user")
            self._note(
                EntryKind.EVENT,
                f"moved by hand to {target}",
                window_id=window_id,
                member_id=member,
            )

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
            )

    def stop_by_hand(self, window_id: str, member_id: str) -> None:
        """Stop a member in mid-travel, by hand."""
        self.world.cover(member_id).stop(self.now)
        self._note(
            EntryKind.EVENT, "stopped by hand", window_id=window_id, member_id=member_id
        )

    def dropout(self, window_id: str, member_id: str, duration: timedelta) -> None:
        """Let a member lose its connection for a while; it returns as it is."""
        self.world.cover(member_id).disconnect(self.now, self.now + duration)
        self._note(
            EntryKind.EVENT,
            f"connectivity dropout for {duration}",
            window_id=window_id,
            member_id=member_id,
        )

    def restart(self) -> None:
        """Throw the core away, rebuild every window from the storage, continue."""
        self.restarts += 1
        self._note(EntryKind.RESTART, "the core restarts; states come from the storage")
        for window in self._windows.values():
            window.engine = self._engine(window.config)
            window.wake_ups.clear()
            self._load(window)
            # The entities are read once at start, as the runtime reads them.
            window.observations = {
                member_id: self.world.cover(member_id).current_observation()
                for member_id in window.member_ids
            }
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
                    cover = self.world.cover(member_id)
                    cover.reports_due(self.now)
                    window.observations[member_id] = cover.current_observation()
                if window.observation().available:
                    self._recompute(window)

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
        """Normalize the reports of the members; say whether an observation changed."""
        changed = False
        for member_id in window.member_ids:
            cover = self.world.cover(member_id)
            for report in cover.reports_due(self.now):
                observation = report.observation()
                if observation == window.observations.get(member_id):
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
        return changed

    # --- One recompute -------------------------------------------------------------------

    def _engine(self, config: WindowConfig) -> Engine:
        return Engine(config, build_arbiter(self._layers))

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
        decision = window.engine.recompute(snapshot)
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
        wake_ups.update(self._expectation_ends(window))
        now = self.now.astimezone(UTC)
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
        wish = decision.winning_wish
        assert wish is not None
        command_ids: dict[str, str] = {}
        stamp = self.now.astimezone(UTC).isoformat(timespec="milliseconds")
        for target in decision.targets:
            if target.position is None:
                continue
            command_id = f"{window.window_id}/{target.member_id}/{stamp}"
            self.world.actuator.move_to(command_id, target.member_id, target.position)
            command_ids[target.member_id] = command_id
            self.record.add(
                Entry(
                    self.now,
                    EntryKind.COMMAND,
                    f"send {target.position.value} ({wish.wish_class.value}, {wish.reason.value})",
                    window_id=window.window_id,
                    member_id=target.member_id,
                    target=target.position,
                    wish_class=wish.wish_class,
                )
            )
        return window.engine.state_after_send(snapshot, decision, command_ids)

    def _expectation_ends(self, window: SimWindow) -> set[datetime]:
        """Return the ends of the expectation windows of the pending commands.

        The gate reads them from the state; the runner wakes the window up at
        each, so a command that the cover did not answer is judged again. For
        a window in dry-run the simulated commands count. The end is the one
        the gate computes, ``member_expectation_end`` of the core, and the
        runner adds nothing of its own: the gate counts a command as pending
        while the time is before the end, so at the end itself it is closed.
        """
        state = window.state
        commands: dict[str, OwnCommand] = (
            {c.member_id: c.command for c in state.simulated.commands}
            if window.controls.dry_run and state.simulated is not None
            else {
                m.member_id: m.last_own_command
                for m in state.members
                if m.last_own_command is not None
            }
        )
        ends: set[datetime] = set()
        for member in window.config.members:
            command = commands.get(member.member_id)
            if command is None:
                continue
            ends.add(member_expectation_end(member, command))
        return ends

    # --- Recording ---------------------------------------------------------------------

    def _note(
        self,
        kind: EntryKind,
        summary: str,
        *,
        window_id: str | None = None,
        member_id: str | None = None,
    ) -> None:
        self.record.add(
            Entry(self.now, kind, summary, window_id=window_id, member_id=member_id)
        )


def _controls_text(controls: Controls) -> str:
    parts = [f"dry_run={controls.dry_run}"]
    for name, level in zip(("global", "group", "window"), controls.levels, strict=True):
        if level.paused or level.maintenance_lock or level.mode.value != "automatic":
            parts.append(
                f"{name}: paused={level.paused} lock={level.maintenance_lock} mode={level.mode.value}"
            )
    return ", ".join(parts)
