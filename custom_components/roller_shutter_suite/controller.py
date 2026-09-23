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
of the schedule, its recheck), the periodic safety tick, and an explicit
request. Every trigger goes through one debouncer per window, so a burst of
changes is coalesced into one recompute and two recomputes of the same
window never run at the same time.

**Wake-up times cannot form a loop.** A time the core asks for is accepted
only if it lies strictly in the future; otherwise it is moved to
``MIN_WAKE_UP_DISTANCE`` from now and the fault is logged once. Recomputes
that come from wake-ups are at least that far apart.

**Start-up:** no decision before the members are available. Late
availability is normal and not an error: the window waits, and when the
cover appears it starts working without a reload.

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

from .capabilities import member_config
from .commands import commands_of, state_with_commands
from .const import COALESCE_SECONDS, MIN_WAKE_UP_DISTANCE, SAFETY_TICK, STARTUP_GRACE
from .core.engine import Engine, build_arbiter
from .core.model import (
    AnySourceValue,
    Controls,
    Decision,
    EvaluationFault,
    FunctionId,
    GateRule,
    MemberCommand,
    ScheduleSettings,
    SunAlmanac,
    WindowConfig,
    WindowObservation,
    WindowState,
    WishClass,
    WorldSnapshot,
)
from .core.ports import Actuator, Clock, Storage, Sun
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
        actuator: Actuator,
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
        self.actuator = actuator
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
        commands = self._send(snapshot, decision, now)
        wake_up = self._schedule_wake_up(_next_wake_up(decision, schedule), now)
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
        self, snapshot: WorldSnapshot, decision: Decision, now: datetime
    ) -> tuple[MemberCommand, ...]:
        """Hand a "send" outcome to the actuator port, after the second dry-run check.

        Every command is written down as the member's own command right after
        its call returned, member by member: if the actuator raises for a
        later member, the commands that were given stay recorded and are not
        sent a second time by the next recompute.
        """
        commands = commands_of(snapshot, decision, now)
        if not commands:
            return ()
        if snapshot.controls.dry_run and not _fire_passed_failed_dry_run(decision):
            _LOGGER.error(
                "Window %s is in dry-run and its decision reached the actuator; "
                "nothing is sent",
                self.title,
            )
            return ()
        for command in commands:
            self.actuator.move_to(
                command.command.command_id, command.member_id, command.command.target
            )
            self._store(state_with_commands(self.state, (command,)))
        return commands

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


def _fire_passed_failed_dry_run(decision: Decision) -> bool:
    """Say whether a fire wish was sent because the dry-run rule itself raised.

    The project owner decided that an escape route that stays closed in a
    fire is the greater evil; the second dry-run check follows that ruling.
    """
    return (
        decision.winning_wish is not None
        and decision.winning_wish.wish_class is WishClass.FIRE
        and any(fault.place is GateRule.DRY_RUN for fault in decision.faults)
    )


def _next_wake_up(decision: Decision, schedule: ScheduleResult | None) -> WakeUp | None:
    """Return the earliest time the core asked for, with its reason."""
    candidates: list[WakeUp] = []
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
