"""Reason events (E8) and the recent decisions of every window.

One event type on the bus, ``roller_shutter_suite_reason``. It is fired when a
layer wants a position and the wish is held back or deferred, when a command
is handed on, and when a window in dry-run would have sent one
(``record.reason_outcome`` says which decisions count). The fire alarm is no
exception and needs none: its wish passes the same path, so under the
maintenance lock or in dry-run its event is fired with the recompute that
sees the alarm, with the reason that says why nothing moved.

**No event storm.** An event is fired when the outcome changes, never again
for the same outcome on the next recompute. The memory of the last outcome
and the list of the recent decisions live in ``hass.data``, next to the
storage of the runtime, so a reload of the entry, which every change of the
configuration causes, does not fire the same outcome again.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN, EVENT_REASON, RECENT_DECISIONS, status_signal
from .controller import Phase
from .core.model import Decision
from .record import ReasonOutcome, reason_outcome
from .runtime import SuiteRuntime

ATTR_SUBENTRY_ID = "subentry_id"
ATTR_DEVICE_ID = "device_id"
ATTR_NAME = "name"


@dataclass(frozen=True, slots=True)
class RecordedDecision:
    """A decision of a window and the time of the recompute that first made it."""

    at: datetime | None
    decision: Decision
    dry_run: bool


def _recent() -> deque[RecordedDecision]:
    return deque(maxlen=RECENT_DECISIONS)


@dataclass(slots=True)
class WindowHistory:
    """What the events remember about one window."""

    last_outcome: tuple[object, ...] | None = None
    recent: deque[RecordedDecision] = field(default_factory=_recent)


HISTORY_KEY: HassKey[dict[str, WindowHistory]] = HassKey(f"{DOMAIN}_history")


def history_of(hass: HomeAssistant) -> dict[str, WindowHistory]:
    """Return the memory of every window, creating it on first use."""
    if HISTORY_KEY not in hass.data:
        hass.data[HISTORY_KEY] = {}
    return hass.data[HISTORY_KEY]


def forget_history(hass: HomeAssistant) -> None:
    """Drop the memory of every window; the entry was removed."""
    hass.data.pop(HISTORY_KEY, None)


@dataclass(slots=True)
class ReasonEvents:
    """Fires the reason events of one window and keeps its recent decisions."""

    hass: HomeAssistant
    runtime: SuiteRuntime
    window_id: str
    name: str
    device_id: str
    history: WindowHistory

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        """Listen to the status of the window; return the remover."""
        return async_dispatcher_connect(
            self.hass, status_signal(self.window_id), self._on_status
        )

    @callback
    def _on_status(self) -> None:
        controller = self.runtime.windows.get(self.window_id)
        if controller is None:
            return
        status = controller.status
        if status.phase is not Phase.RUNNING or status.decision is None:
            return
        dry_run = controller.controls().dry_run
        self._remember(status.decision, dry_run, status.last_recompute)
        outcome = reason_outcome(
            status.decision, sent=bool(status.commands), dry_run=dry_run
        )
        if outcome is None:
            self.history.last_outcome = None
        elif (
            isinstance(outcome, ReasonOutcome)
            and outcome.key != self.history.last_outcome
        ):
            self.history.last_outcome = outcome.key
            self._fire(outcome)

    def _remember(self, decision: Decision, dry_run: bool, at: datetime | None) -> None:
        recent = self.history.recent
        if recent and recent[0].decision == decision and recent[0].dry_run is dry_run:
            return
        recent.appendleft(RecordedDecision(at, decision, dry_run))

    def _fire(self, outcome: ReasonOutcome) -> None:
        self.hass.bus.async_fire(
            EVENT_REASON,
            {
                ATTR_SUBENTRY_ID: self.window_id,
                ATTR_DEVICE_ID: self.device_id,
                ATTR_NAME: self.name,
                **outcome.as_event_data(),
            },
        )
