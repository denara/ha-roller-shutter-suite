"""The window controller: feeds the core and calls it for one window.

One controller per window that is set up. It is the thin adapter of
guardrail 4 on the input side: it turns the entities the window uses, the
time and the sun into a ``WorldSnapshot``, asks the engine of the core for a
decision, hands what the gate lets through to the actuator port, persists
the state the decision leaves behind, and decides when the window is looked
at next. It contains no rule about shutters; ``docs/dev/runtime.md``
describes its life cycle.

**Triggers of a recompute:** a state change of an entity the window uses
(its members and its sources), a point in time the core asked for (the end
of a deferral, the upper bound of a re-evaluation, the next planned action
of the schedule, its recheck), the end of the expectation window of a
pending own command (``member_expectation_end`` of the core, the same
deadline the gate reads), the periodic safety tick, and an explicit
request. Every trigger goes through one debouncer per window, so a burst of
changes is coalesced into one recompute and two recomputes of the same
window never run at the same time.

**Wake-up times cannot form a loop.** A time the core asks for is accepted
only if it lies strictly in the future; otherwise it is moved to
``MIN_WAKE_UP_DISTANCE`` from now and the fault is logged once. Recomputes
that come from wake-ups are at least that far apart.

**Start-up:** no decision before the members are available. Late
availability is normal and not an error: the window waits, and when the
cover appears it starts working without a reload. With several members and
at least one available, the window decides with what is known once
``STARTUP_GRACE`` has passed; a member that has not reported by then stays
unknown and is the gate's business (``docs/dev/runtime.md``, "Deviations").

**Capabilities are never re-read**, with one exception: a member about
which nothing was known at set-up (no usable state and no entity-registry
entry, so its profile says ``capabilities_known=False``) has its
capabilities read from the entity once, the first time it is available.
A known profile is never read again, so nothing flaps while an entity is
away.

**Faults of the arbiter's safety net** (``Decision.faults``) are logged
once per change, with the window's name, the stage, the place and the type
of the exception, never its message, and they are part of the status.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from enum import StrEnum, unique
from typing import Final
from uuid import uuid4

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_time_interval,
)

from .actuator import (
    CoverActuator,
    MemberActuator,
    WindowActuator,
    fire_passed_failed_dry_run,
)
from .capabilities import member_config
from .const import COALESCE_SECONDS, MIN_WAKE_UP_DISTANCE, SAFETY_TICK, STARTUP_GRACE
from .core.arbiter import member_expectation_end
from .core.engine import Engine, build_arbiter
from .core.model import (
    AnySourceValue,
    CommandResult,
    Controls,
    Decision,
    EvaluationFault,
    FunctionId,
    GateKind,
    MemberCommand,
    OwnCommand,
    Position,
    ScheduleSettings,
    SunAlmanac,
    WindowConfig,
    WindowObservation,
    WindowState,
    WorldSnapshot,
)
from .core.ports import Clock, Storage, Sun
from .core.schedule import (
    ScheduleInputMissingError,
    ScheduleResult,
    build_sun_almanac,
    evaluate_schedule,
)
from .members import observe_window
from .sources import SourceReference, read_sources, window_sources
from .storage import installation_seed

_LOGGER = logging.getLogger(__name__)

WAKE_UP_DEFERRED: Final = "deferred_until"
WAKE_UP_REEVALUATE: Final = "reevaluate_no_later_than"
WAKE_UP_NEXT_ACTION: Final = "next_planned_action"
WAKE_UP_RECHECK: Final = "schedule_recheck"
WAKE_UP_STARTUP_GRACE: Final = "startup_grace"
WAKE_UP_EXPECTATION_END: Final = "expectation_window_end"


@unique
class Phase(StrEnum):
    """Where a window controller is in its life cycle."""

    WAITING_FOR_MEMBERS = "waiting_for_members"
    """Started, no decision yet: the members are not available."""
    RUNNING = "running"
    """Decides on every trigger."""
    STOPPED = "stopped"
    """Not started, or stopped: no listener, no timer."""


@dataclass(frozen=True, slots=True)
class SourceReading:
    """The value of a source, and since when the integration has seen it.

    ``since`` is the integration's own timestamp: the time of the first
    recompute that saw this value, in UTC. It is never the change time of
    the entity, which after a restart is the time of the restore.
    """

    value: AnySourceValue
    since: datetime


@dataclass(frozen=True, slots=True)
class WakeUp:
    """A point in time at which the window is recomputed, and why."""

    at: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class WindowStatus:
    """The facts about a window for the entities of a later block.

    ``faults`` are the layers, constraints and gate rules that raised
    during the last recompute; ``error`` names the type of an exception that
    the recompute itself raised, outside the safety net of the arbiter.
    ``disabled_functions`` are the comfort functions that a faulty stored
    setting switched off for this window. ``commands`` are the commands the
    last recompute handed to the actuator port.
    """

    phase: Phase
    observation: WindowObservation | None = None
    decision: Decision | None = None
    faults: tuple[EvaluationFault, ...] = ()
    disabled_functions: frozenset[FunctionId] = frozenset()
    sources: Mapping[str, SourceReading] = field(default_factory=dict)
    schedule: ScheduleResult | None = None
    commands: tuple[MemberCommand, ...] = ()
    wake_up: WakeUp | None = None
    recomputes: int = 0
    last_recompute: datetime | None = None
    error: str | None = None


class WindowController:
    """Feeds the core with the world of one window and calls it."""

    def __init__(  # noqa: PLR0913 - the ports of the core are the input
        self,
        hass: HomeAssistant,
        *,
        window_id: str,
        title: str,
        config: WindowConfig,
        clock: Clock,
        sun: Sun,
        storage: Storage,
        actuator: CoverActuator,
        controls: Callable[[], Controls],
        engine: Engine | None = None,
    ) -> None:
        """Create the controller; nothing listens until :meth:`async_start`."""
        self.hass = hass
        self.window_id = window_id
        self.title = title
        self.config = config
        self.clock = clock
        self.sun = sun
        self.storage = storage
        self.hub = actuator
        self.actuator: MemberActuator | None = None
        """The actuator port of this window, bound while the controller runs."""
        self.controls = controls
        self.engine = Engine(config, build_arbiter()) if engine is None else engine
        self.state = WindowState()
        self.status = WindowStatus(Phase.STOPPED)
        self.sources: dict[str, SourceReference | None] = window_sources(config)
        self._readings: dict[str, SourceReading] = {}
        self._subscriptions: list[CALLBACK_TYPE] = []
        self._wake_up: CALLBACK_TYPE | None = None
        self._almanac: tuple[date, ScheduleSettings, SunAlmanac] | None = None
        self._logged_faults: frozenset[EvaluationFault] = frozenset()
        self._refusal_logged = False
        self._started_at: datetime | None = None
        self._loaded = False
        self._last_wake_up: datetime | None = None
        self._woken = False
        self._binding: WindowActuator | None = None
        self._debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=COALESCE_SECONDS,
            immediate=False,
            function=self._recompute,
        )

    # ------------------------------------------------------------------
    # Life cycle
    # ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        """Return whether the controller listens and keeps timers."""
        return bool(self._subscriptions)

    @callback
    def async_start(self) -> None:
        """Load the state, listen to the entities of the window, start the tick."""
        self._load_state()
        # Bound after the state is loaded: results that arrived while the
        # window had no controller are handed over at once.
        self._binding = self.hub.bind(
            self.window_id,
            title=self.title,
            controls=self.controls,
            gap=self.config.stagger_gap,
            on_result=self._on_command_result,
        )
        self.actuator = self._binding
        self._started_at = self.clock.now()
        entity_ids = [member.member_id for member in self.config.members]
        entity_ids.extend(
            reference.entity_id
            for reference in self.sources.values()
            if reference is not None
        )
        self._subscriptions.append(
            async_track_state_change_event(self.hass, entity_ids, self._on_state_change)
        )
        self._subscriptions.append(
            async_track_time_interval(
                self.hass, self._on_tick, SAFETY_TICK, name=f"{self.title} safety tick"
            )
        )
        self.status = WindowStatus(Phase.WAITING_FOR_MEMBERS)
        self.async_request_recompute()

    @callback
    def async_stop(self) -> None:
        """Cancel every listener and timer and save the state."""
        for unsubscribe in self._subscriptions:
            unsubscribe()
        self._subscriptions.clear()
        self._cancel_wake_up()
        self._debouncer.async_shutdown()
        if self._binding is not None:
            self._binding.release()
            self._binding = None
        self.actuator = None
        if self._loaded:
            # Never write a fresh state over a stored one that was not read.
            self.storage.save_window_state(self.window_id, self.state.to_data())
        self.status = replace(self.status, phase=Phase.STOPPED, wake_up=None)

    @callback
    def async_request_recompute(self) -> None:
        """Ask for a recompute; a burst of requests yields one."""
        self._debouncer.async_schedule_call()

    # ------------------------------------------------------------------
    # Triggers
    # ------------------------------------------------------------------

    @callback
    def _on_state_change(self, event: Event[EventStateChangedData]) -> None:
        del event
        self.async_request_recompute()

    @callback
    def _on_tick(self, now: datetime) -> None:
        del now
        self.async_request_recompute()

    @callback
    def _on_wake_up(self, now: datetime) -> None:
        del now
        # The timer has fired; cancelling it now is a no-op that lets the
        # remover go, so every timer is released through the same call.
        self._cancel_wake_up()
        self._woken = True
        self.async_request_recompute()

    def _cancel_wake_up(self) -> None:
        if self._wake_up is not None:
            self._wake_up()
            self._wake_up = None

    def _schedule_wake_up(self, wake_up: WakeUp | None, now: datetime) -> WakeUp | None:
        """Arm the timer for the next wake-up; return it as accepted."""
        self._cancel_wake_up()
        if wake_up is None:
            return None
        at = wake_up.at
        if at <= now:
            if not self._refusal_logged:
                _LOGGER.warning(
                    "Window %s: the core asked to be woken at %s, which is not after "
                    "%s; the wake-up is moved to %s from now. This is logged once",
                    self.title,
                    at.isoformat(),
                    now.isoformat(),
                    MIN_WAKE_UP_DISTANCE,
                )
                self._refusal_logged = True
            at = now + MIN_WAKE_UP_DISTANCE
        else:
            self._refusal_logged = False
        if self._last_wake_up is not None:
            at = max(at, self._last_wake_up + MIN_WAKE_UP_DISTANCE)
        accepted = WakeUp(at, wake_up.reason)
        self._wake_up = async_track_point_in_utc_time(self.hass, self._on_wake_up, at)
        return accepted

    # ------------------------------------------------------------------
    # The recompute
    # ------------------------------------------------------------------

    @callback
    def _recompute(self) -> None:
        """Run one recompute; never let an exception out."""
        woken, self._woken = self._woken, False
        now = self.clock.now()
        if woken:
            self._last_wake_up = now
        try:
            self._decide(now)
        except Exception as error:
            if self.status.error != type(error).__name__:
                # A programming error: the traceback, which carries the text
                # of the exception, belongs in the log. The message line
                # itself names only the type; nothing here becomes an issue.
                _LOGGER.exception(
                    "Window %s: the recompute raised %s; the window keeps its state "
                    "and is evaluated again at the next trigger",
                    self.title,
                    type(error).__name__,
                )
            self.status = replace(
                self.status, error=type(error).__name__, last_recompute=now
            )

    def _members_ready(self, observation: WindowObservation, now: datetime) -> bool:
        """Say whether the first decision may be made.

        All members available: yes. None: no. Some: once the start-up grace
        has passed. After the first decision the gate handles a member that
        is away.
        """
        if self.status.phase is Phase.RUNNING:
            return True
        states = [member.observation.available for member in observation.members]
        if all(states):
            return True
        if not any(states) or self._started_at is None:
            return False
        return now >= self._started_at + STARTUP_GRACE

    def _learn_unknown_capabilities(self) -> None:
        """Read the capabilities of a member that was unknown, once it is available.

        The one exception to "capabilities are never re-read": a member with
        ``capabilities_known=False`` is read from its entity the first time
        it is available, and the configuration and the engine are replaced
        with the learned profile. A known profile is never read again.
        """
        members = list(self.config.members)
        changed = False
        for index, member in enumerate(members):
            if member.capabilities.capabilities_known:
                continue
            state = self.hass.states.get(member.member_id)
            if state is None or state.state == STATE_UNAVAILABLE:
                continue
            learned = member_config(self.hass, member.member_id)
            if not learned.capabilities.capabilities_known:
                continue
            members[index] = replace(member, capabilities=learned.capabilities)
            changed = True
        if changed:
            self.config = replace(self.config, members=tuple(members))
            self.engine = Engine(self.config, self.engine.arbiter)

    def _decide(self, now: datetime) -> None:
        self._learn_unknown_capabilities()
        observation = observe_window(self.hass, self.config)
        if not self._members_ready(observation, now):
            wake_up = None
            if observation.available and self._started_at is not None:
                wake_up = WakeUp(
                    self._started_at + STARTUP_GRACE, WAKE_UP_STARTUP_GRACE
                )
            self.status = replace(
                self.status,
                phase=Phase.WAITING_FOR_MEMBERS,
                observation=observation,
                last_recompute=now,
                wake_up=self._schedule_wake_up(wake_up, now),
                error=None,
            )
            return
        readings = self._read_sources(now)
        snapshot = WorldSnapshot(
            time=now,
            sun=self.sun.position(now),
            sources={key: reading.value for key, reading in readings.items()},
            observation=observation,
            state=self.state,
            controls=self.controls(),
            almanac=self._almanac_for(now),
            installation_seed=installation_seed(self.storage),
        )
        decision = self.engine.recompute(snapshot)
        self._log_faults(decision.faults)
        state = self.engine.state_after(snapshot, decision)
        schedule = self._schedule(replace(snapshot, state=state))
        if schedule is not None:
            state = schedule.state
        self._store(state)
        # The send is recorded on top of the state the decision left behind.
        commands = self._send(replace(snapshot, state=self.state), decision)
        wake_up = self._schedule_wake_up(
            _next_wake_up(decision, schedule, self._expectation_ends(now)), now
        )
        self.status = WindowStatus(
            phase=Phase.RUNNING,
            observation=observation,
            decision=decision,
            faults=decision.faults,
            disabled_functions=self.config.disabled_functions,
            sources=dict(readings),
            schedule=schedule,
            commands=commands,
            wake_up=wake_up,
            recomputes=self.status.recomputes + 1,
            last_recompute=now,
        )

    def _read_sources(self, now: datetime) -> dict[str, SourceReading]:
        """Read every source; a value that changed gets the time of this reading."""
        values = read_sources(self.hass, self.sources)
        for key, value in values.items():
            known = self._readings.get(key)
            if known is None or known.value != value:
                self._readings[key] = SourceReading(value, now.astimezone(UTC))
        return dict(self._readings)

    def _almanac_for(self, now: datetime) -> SunAlmanac:
        """Return the almanac; build it again when the date or the settings change."""
        key = (now.date(), self.config.schedule)
        if self._almanac is None or self._almanac[:2] != key:
            almanac = build_sun_almanac(self.config, now, self.sun)
            self._almanac = (key[0], key[1], almanac)
        return self._almanac[2]

    def _schedule(self, snapshot: WorldSnapshot) -> ScheduleResult | None:
        """Evaluate the schedule for its state and its times, as the layer does.

        Only while the schedule runs for the window: switched on, not paused
        by a faulty setting, and with every input it needs. The state it
        returns is what ``schedule_state_after`` would return; the next
        planned action and the recheck are the wake-ups.
        """
        if (
            not self.config.schedule_enabled
            or FunctionId.SCHEDULE in self.config.disabled_functions
        ):
            return None
        try:
            return evaluate_schedule(self.config, snapshot)
        except ScheduleInputMissingError:
            return None

    def _send(
        self, snapshot: WorldSnapshot, decision: Decision
    ) -> tuple[MemberCommand, ...]:
        """Hand a "send" outcome to the actuator port, after the second dry-run check.

        ``snapshot.state`` is the state the decision left behind. Every member
        with a target gets a fresh command identifier. The core records the
        send (``Engine.state_after_send``, the one recorder of own commands),
        and it is called right after each member's call returned, with the
        identifiers of every member sent so far: if the actuator raises for a
        later member, the commands that were given stay recorded and are not
        sent a second time by the next recompute.
        """
        targets = _targets_to_send(self.config, snapshot, decision)
        if not targets or self.actuator is None:
            return ()
        if snapshot.controls.dry_run and not fire_passed_failed_dry_run(decision):
            _LOGGER.error(
                "Window %s is in dry-run and its decision reached the actuator; "
                "nothing is sent",
                self.title,
            )
            return ()
        command_ids: dict[str, str] = {}
        for member_id, position in targets:
            command_id = uuid4().hex
            self.actuator.move_to(command_id, member_id, position, decision=decision)
            command_ids[member_id] = command_id
            self._store(Engine.state_after_send(snapshot, decision, command_ids))
        return tuple(
            MemberCommand(member.member_id, member.last_own_command)
            for member in self.state.members
            if member.member_id in command_ids and member.last_own_command is not None
        )

    @callback
    def _on_command_result(self, result: CommandResult) -> None:
        """Record what the actuator reported: the context ID, or ``command_failed``.

        The core writes it into the member's last own command
        (``Engine.on_command_result``) and ignores a late result of an older
        command. Nothing is retried here; a failed command stays pending
        until its expectation window has closed, and "target reached" does
        not count it.
        """
        state = Engine.on_command_result(self.state, result)
        if state is self.state:
            return
        self._store(state)
        commands = {m.member_id: m.last_own_command for m in state.members}
        self.status = replace(
            self.status,
            commands=tuple(
                MemberCommand(item.member_id, command)
                if (command := commands.get(item.member_id)) is not None
                and command.command_id == item.command.command_id
                else item
                for item in self.status.commands
            ),
        )

    def _expectation_ends(self, now: datetime) -> tuple[datetime, ...]:
        """Return the ends of the expectation windows that still lie ahead.

        One per pending own command of a member of the window (the simulated
        ones for a window in dry-run), each computed by the core's
        ``member_expectation_end``, the deadline the gate reads. The window
        is woken at each, so a command the cover did not answer is judged
        again at the instant the gate stops counting it as pending.
        """
        commands: dict[str, OwnCommand] = (
            {c.member_id: c.command for c in self.state.simulated.commands}
            if self.controls().dry_run and self.state.simulated is not None
            else {
                m.member_id: m.last_own_command
                for m in self.state.members
                if m.last_own_command is not None
            }
        )
        ends = (
            member_expectation_end(member, commands[member.member_id])
            for member in self.config.members
            if member.member_id in commands
        )
        return tuple(end for end in ends if end > now)

    # ------------------------------------------------------------------
    # State and faults
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        data = self.storage.load_window_state(self.window_id)
        state = WindowState()
        if data is not None:
            try:
                state = WindowState.from_data(data)
            except (TypeError, ValueError) as error:
                _LOGGER.error(  # noqa: TRY400 - the type is enough, the message could carry data
                    "Window %s: the stored state cannot be read (%s); the window "
                    "starts with a fresh state",
                    self.title,
                    type(error).__name__,
                )
        if not self.controls().dry_run and state.simulated is not None:
            state = Engine.arm(state)
        self.state = state
        self._loaded = True

    def _store(self, state: WindowState) -> None:
        if state == self.state:
            return
        self.state = state
        self.storage.save_window_state(self.window_id, state.to_data())

    def _log_faults(self, faults: tuple[EvaluationFault, ...]) -> None:
        """Log every fault once, when it appears; and once when all are gone."""
        current = frozenset(faults)
        for fault in faults:
            if fault not in self._logged_faults:
                _LOGGER.warning(
                    "Window %s: the %s %s%s raised %s during a recompute; the "
                    "arbiter applied the cautious outcome of that stage",
                    self.title,
                    fault.stage.value,
                    fault.place.value,
                    "" if fault.function is None else f" ({fault.function.value})",
                    fault.error,
                )
        if self._logged_faults and not current:
            _LOGGER.info(
                "Window %s: the recompute runs without a fault again", self.title
            )
        self._logged_faults = current


def _targets_to_send(
    config: WindowConfig, snapshot: WorldSnapshot, decision: Decision
) -> tuple[tuple[str, Position], ...]:
    """Return the member targets of a "send" outcome; none for any other outcome.

    A send commands only the members that are available (section 9 of the
    specification: the others are commanded, the unavailable one is not)
    and that do not stand at their target within their tolerance. A member
    that reports no position cannot be judged and is commanded. A member
    that is not commanded gets no record; the core leaves a member without a
    command identifier alone. The duplicate part of the gate rule "movement
    in flight" judges the same members, so a member that already stands
    where it should does not make a pending command look like a new one.
    Until the core names the commanded members itself (block C06), this
    filter lives here.
    """
    if (
        decision.gate is None
        or decision.gate.kind is not GateKind.SEND
        or decision.winning_wish is None
    ):
        return ()
    reported = {
        member.member_id: member.observation.position
        for member in snapshot.observation.members
        if member.observation.available
    }
    tolerances = {
        member.member_id: member.capabilities.tolerance for member in config.members
    }
    return tuple(
        (target.member_id, target.position)
        for target in decision.targets
        if target.position is not None
        and target.member_id in reported
        and not _stands_at(
            reported[target.member_id],
            target.position,
            tolerances.get(target.member_id, 0),
        )
    )


def _stands_at(position: Position | None, target: Position, tolerance: int) -> bool:
    return position is not None and abs(position.value - target.value) <= tolerance


def _next_wake_up(
    decision: Decision,
    schedule: ScheduleResult | None,
    expectation_ends: tuple[datetime, ...],
) -> WakeUp | None:
    """Return the earliest time the core asked for, with its reason."""
    candidates: list[WakeUp] = [
        WakeUp(end, WAKE_UP_EXPECTATION_END) for end in expectation_ends
    ]
    if decision.gate is not None:
        if decision.gate.until is not None:
            candidates.append(WakeUp(decision.gate.until, WAKE_UP_DEFERRED))
        if decision.gate.reevaluate_no_later_than is not None:
            candidates.append(
                WakeUp(decision.gate.reevaluate_no_later_than, WAKE_UP_REEVALUATE)
            )
    if schedule is not None:
        if schedule.next_action is not None:
            candidates.append(WakeUp(schedule.next_action.at, WAKE_UP_NEXT_ACTION))
        if schedule.recheck_at is not None:
            candidates.append(WakeUp(schedule.recheck_at, WAKE_UP_RECHECK))
    if not candidates:
        return None
    return min(candidates, key=lambda wake_up: wake_up.at)
