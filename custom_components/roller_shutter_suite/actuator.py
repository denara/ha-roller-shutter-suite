"""The cover actuator adapter: the only place that moves a cover (G1).

Nothing else in the integration calls a cover action; a test scans the
source and fails on any other occurrence. Keeping it in one small place is
what makes dry-run trustworthy: if nothing else can send a command, a window
in dry-run provably does not move.

**What it does with a command.** The window controller hands every member
target of a "send" decision to :meth:`WindowActuator.move_to`, the actuator
port of the core for one window, together with the decision. The adapter

1. checks dry-run a second time (defense in depth): a window in dry-run
   sends nothing, with the one exception the project owner decided, a fire
   command whose decision names the failed dry-run rule
   (:func:`fire_passed_failed_dry_run`, ``docs/architecture.md`` section 13a).
   The check runs when the command arrives and again right before the call;
2. gives the command its slot in a collective movement (staggering, E13):
   after each motor the next one waits the gap of the window the motor
   belongs to, across windows and between the members of one window. Fire is
   never staggered;
3. translates the target into what the cover supports, read from its state
   at the moment of the call: ``set_cover_position`` where it can be set to a
   position; otherwise ``open_cover`` from 50 upwards and ``close_cover``
   below 50 (section 8.1). It never calls an action the cover does not
   support;
4. calls the action under a context of its own, waits for the call to
   return, and reports the result to the controller with the context ID and
   the instant of the call (``called_at``, where a staggered command's
   expectation window starts): accepted, or ``command_failed`` if the call
   raised, could not be made, or a dry-run check refused it. A failure is logged
   once per member with the window's name, until a call to it works again.
   Nothing here retries; command verification and backoff are a later block.

A result says only whether the actuator accepted the command. Nothing here
claims that a curtain has arrived: on many installations the reported
position is calculated from run time.

**Lifetime.** The adapter lives in ``hass.data`` like the storage and
survives the reload of the config entry, so a command that is queued or
under way during a reload is still sent, and its result reaches the
controller that runs the window after the reload. A result for a window
without a controller at that moment is kept (the latest per member) and
handed over when the window is bound again. When Home Assistant stops or the
entry is removed, queued commands are dropped and reported as failed.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final, Protocol

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverEntityFeature,
)
from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    EVENT_HOMEASSISTANT_STOP,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    SERVICE_SET_COVER_POSITION,
    STATE_UNAVAILABLE,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Context,
    Event,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN
from .core.model import (
    CommandResult,
    Controls,
    Decision,
    GateRule,
    Position,
    WishClass,
)

_LOGGER = logging.getLogger(__name__)

ACTUATOR_KEY: HassKey[CoverActuator] = HassKey(f"{DOMAIN}_actuator")

HALFWAY: Final = 50
"""A cover without "set position" is opened from here upwards, closed below."""

type ResultSink = Callable[[CommandResult], None]


def fire_passed_failed_dry_run(decision: Decision | None) -> bool:
    """Say whether a fire wish was sent because the dry-run rule itself raised.

    The project owner decided that an escape route that stays closed in a
    fire is the greater evil; the second dry-run check follows that ruling
    and lets exactly this command through for a window in dry-run.
    """
    return (
        decision is not None
        and decision.winning_wish is not None
        and decision.winning_wish.wish_class is WishClass.FIRE
        and any(fault.place is GateRule.DRY_RUN for fault in decision.faults)
    )


def is_fire(decision: Decision | None) -> bool:
    """Say whether the command carries a fire wish, which is never staggered."""
    return (
        decision is not None
        and decision.winning_wish is not None
        and decision.winning_wish.wish_class is WishClass.FIRE
    )


def cover_action(state: State | None, target: Position) -> tuple[str, dict[str, Any]]:
    """Return the cover action and its data for a target, from the cover's state.

    Set position where the cover supports it; otherwise open from
    :data:`HALFWAY` upwards and close below it, if the cover supports that.
    Raise :class:`CommandNotPossibleError` if the cover is away or supports
    none of it.
    """
    if state is None or state.state == STATE_UNAVAILABLE:
        raise CommandNotPossibleError("the cover is unavailable")
    raw = state.attributes.get(ATTR_SUPPORTED_FEATURES, 0)
    features = CoverEntityFeature(raw if isinstance(raw, int) else 0)
    if CoverEntityFeature.SET_POSITION in features:
        return SERVICE_SET_COVER_POSITION, {ATTR_POSITION: target.value}
    if target.value >= HALFWAY:
        service, needed = SERVICE_OPEN_COVER, CoverEntityFeature.OPEN
    else:
        service, needed = SERVICE_CLOSE_COVER, CoverEntityFeature.CLOSE
    if needed not in features:
        raise CommandNotPossibleError("the cover supports no action for this target")
    return service, {}


class CommandNotPossibleError(Exception):
    """The cover cannot execute the command: it is away or lacks the action."""


class MemberActuator(Protocol):
    """What the window controller calls: the actuator port plus the decision."""

    def move_to(
        self,
        command_id: str,
        member_id: str,
        target: Position,
        *,
        decision: Decision | None = None,
    ) -> None:
        """Command one member to a position; return without waiting."""


@dataclass(slots=True)
class WindowActuator:
    """The actuator port of the core for one window.

    It satisfies ``core.ports.Actuator``; the controller also hands in the
    decision, which the second dry-run check and the staggering need. A
    command without a decision is treated as what it cannot prove not to
    be: a window in dry-run sends nothing for it, and it is staggered.
    """

    hub: CoverActuator
    window_id: str
    title: str
    controls: Callable[[], Controls]
    gap: timedelta
    on_result: ResultSink

    def move_to(
        self,
        command_id: str,
        member_id: str,
        target: Position,
        *,
        decision: Decision | None = None,
    ) -> None:
        """Queue the command for its slot; nothing is sent while in dry-run."""
        self.hub.submit(self, _Command(command_id, member_id, target, decision))

    def release(self) -> None:
        """Stop receiving results; queued commands of the window stay queued."""
        self.hub.release(self)


@dataclass(frozen=True, slots=True)
class _Command:
    command_id: str
    member_id: str
    target: Position
    decision: Decision | None


@dataclass(slots=True)
class _Queued:
    window_id: str
    command: _Command
    cancel: CALLBACK_TYPE


@dataclass(slots=True)
class CoverActuator:
    """The one adapter that calls cover actions, shared by every window."""

    hass: HomeAssistant
    _bindings: dict[str, WindowActuator] = field(default_factory=dict)
    _queued: dict[str, _Queued] = field(default_factory=dict)
    _undelivered: dict[str, dict[str, CommandResult]] = field(default_factory=dict)
    _failing: set[str] = field(default_factory=set)
    _next_free: datetime | None = None

    # -- Windows ------------------------------------------------------------------

    @callback
    def bind(
        self,
        window_id: str,
        *,
        title: str,
        controls: Callable[[], Controls],
        gap: timedelta,
        on_result: ResultSink,
    ) -> WindowActuator:
        """Return the actuator port of a window; results reach ``on_result``.

        Results that arrived while the window had no controller are handed
        over now, the latest per member.
        """
        binding = WindowActuator(self, window_id, title, controls, gap, on_result)
        self._bindings[window_id] = binding
        for result in self._undelivered.pop(window_id, {}).values():
            on_result(result)
        return binding

    @callback
    def release(self, binding: WindowActuator) -> None:
        """Forget a binding, unless a newer one of the same window replaced it."""
        if self._bindings.get(binding.window_id) is binding:
            del self._bindings[binding.window_id]

    # -- Commands -----------------------------------------------------------------

    @callback
    def submit(self, binding: WindowActuator, command: _Command) -> None:
        """Check dry-run, give the command its slot, and start or queue it.

        A refusal is reported like the refusal right before the call: as a
        failed command, after the caller has returned (a result never
        arrives before the caller recorded the command).
        """
        if not _may_send(binding, command):
            self.hass.loop.call_soon(
                self._deliver, binding.window_id, _result(command, None, failed=True)
            )
            return
        previous = self._queued.pop(command.member_id, None)
        if previous is not None:
            # A newer own command replaces the queued one as a whole.
            previous.cancel()
        now = dt_util.utcnow()
        if is_fire(command.decision):
            self._start(binding.window_id, command)
            return
        slot = now if self._next_free is None else max(now, self._next_free)
        self._next_free = slot + binding.gap
        if slot <= now:
            self._start(binding.window_id, command)
            return

        @callback
        def _at_slot(_now: datetime) -> None:
            queued = self._queued.get(command.member_id)
            if queued is not None and queued.command is command:
                del self._queued[command.member_id]
                self._start(binding.window_id, command)

        self._queued[command.member_id] = _Queued(
            binding.window_id,
            command,
            async_track_point_in_utc_time(self.hass, _at_slot, slot),
        )

    @callback
    def _start(self, window_id: str, command: _Command) -> None:
        """Start the call as a task of its own; it runs after the caller returns."""
        self.hass.async_create_task(
            self._call(window_id, command),
            name=f"{DOMAIN} command to {command.member_id}",
            eager_start=False,
        )

    async def _call(self, window_id: str, command: _Command) -> None:
        """Check dry-run once more, call the action, report the result."""
        binding = self._bindings.get(window_id)
        if binding is None:
            _LOGGER.warning(
                "A command to %s was dropped: its window is not running",
                command.member_id,
            )
            self._deliver(window_id, _result(command, None, failed=True))
            return
        if not _may_send(binding, command):
            self._deliver(window_id, _result(command, None, failed=True))
            return
        context = Context()
        called_at: datetime | None = None
        try:
            service, data = cover_action(
                self.hass.states.get(command.member_id), command.target
            )
            called_at = dt_util.utcnow()
            await self.hass.services.async_call(
                COVER_DOMAIN,
                service,
                {ATTR_ENTITY_ID: command.member_id, **data},
                blocking=True,
                context=context,
            )
        except Exception as error:  # noqa: BLE001 - every error of the call is command_failed
            self._log_failure(binding.title, command.member_id, error)
            self._deliver(
                window_id, _result(command, context.id, failed=True, at=called_at)
            )
            return
        if command.member_id in self._failing:
            self._failing.discard(command.member_id)
            _LOGGER.info(
                "Window %s: the cover %s accepts commands again",
                binding.title,
                command.member_id,
            )
        self._deliver(
            window_id, _result(command, context.id, failed=False, at=called_at)
        )

    def _log_failure(self, title: str, member_id: str, error: Exception) -> None:
        """Log a failed call once per member, until a call works again."""
        if member_id in self._failing:
            return
        self._failing.add(member_id)
        _LOGGER.warning(
            "Window %s: the command to %s failed (%s); it is reported to the "
            "core as a failed command. Further failures of this cover are not "
            "logged until a command works again",
            title,
            member_id,
            type(error).__name__,
        )

    @callback
    def _deliver(self, window_id: str, result: CommandResult) -> None:
        binding = self._bindings.get(window_id)
        if binding is None:
            self._undelivered.setdefault(window_id, {})[result.member_id] = result
            return
        binding.on_result(result)

    # -- Shutdown -----------------------------------------------------------------

    @callback
    def async_shutdown(self) -> None:
        """Drop every queued command and report it as failed; nothing was sent."""
        queued, self._queued = self._queued, {}
        for entry in queued.values():
            entry.cancel()
            self._deliver(entry.window_id, _result(entry.command, None, failed=True))
        self._next_free = None


def _result(
    command: _Command,
    context_id: str | None,
    *,
    failed: bool,
    at: datetime | None = None,
) -> CommandResult:
    return CommandResult(
        command.command_id, command.member_id, context_id, failed, called_at=at
    )


def _may_send(binding: WindowActuator, command: _Command) -> bool:
    """Check dry-run a second time; refuse and say so."""
    if not binding.controls().dry_run or fire_passed_failed_dry_run(command.decision):
        return True
    _LOGGER.error(
        "Window %s is in dry-run and a command to %s reached the actuator; "
        "nothing is sent",
        binding.title,
        command.member_id,
    )
    return False


def actuator_of(hass: HomeAssistant) -> CoverActuator:
    """Return the actuator of the installation, creating it on first use."""
    if ACTUATOR_KEY not in hass.data:
        actuator = CoverActuator(hass)
        hass.data[ACTUATOR_KEY] = actuator

        @callback
        def _on_stop(_event: Event) -> None:
            actuator.async_shutdown()

        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop)
    return hass.data[ACTUATOR_KEY]


@callback
def forget_actuator(hass: HomeAssistant) -> None:
    """Drop the actuator; the entry it belonged to was removed."""
    actuator = hass.data.pop(ACTUATOR_KEY, None)
    if actuator is not None:
        actuator.async_shutdown()
