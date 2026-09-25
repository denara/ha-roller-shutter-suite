"""What the tests of the status share: entity IDs, a stub fire alarm, controls.

The arbiter of the integration has no fire layer yet. The tests of the fire
event give a window an engine whose arbiter has the layers of the feature
blocks plus a stub fire layer that wants "fully open" while the test says the
alarm is on (:class:`FireAlarm`). The gate rules are the real ones, so the
maintenance lock and dry-run decide as they will in the finished integration.
"""

from dataclasses import dataclass
from typing import Any

from homeassistant.core import Event, HomeAssistant, State, callback

from custom_components.roller_shutter_suite.const import EVENT_REASON
from custom_components.roller_shutter_suite.controller import WindowController
from custom_components.roller_shutter_suite.core.arbiter import LayerRegistration
from custom_components.roller_shutter_suite.core.engine import (
    FEATURE_LAYERS,
    Engine,
    build_arbiter,
)
from custom_components.roller_shutter_suite.core.model import (
    FULLY_OPEN,
    ControlLevel,
    Controls,
    FunctionId,
    Layer,
    WindowConfig,
    Wish,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode

REASON = "sensor.example_window_reason"
TARGET = "sensor.example_window_target_position"
NEXT_ACTION = "sensor.example_window_next_planned_action"
OVERRIDE = "binary_sensor.example_window_manual_override"
DRY_RUN = "binary_sensor.example_window_dry_run"
ENTITIES = (REASON, TARGET, NEXT_ACTION, OVERRIDE, DRY_RUN)


@dataclass
class FireAlarm:
    """A fire alarm the test switches; the stub layer reads it."""

    active: bool = False

    def layer(self, config: WindowConfig, world: WorldSnapshot) -> Wish:
        """Open fully while the alarm is on; no opinion otherwise."""
        del config, world
        if self.active:
            return Wish.target(Layer.FIRE, ReasonCode.FIRE_ALARM, FULLY_OPEN)
        return Wish.no_opinion(Layer.FIRE, ReasonCode.INACTIVE)

    def install(self, controller: WindowController) -> None:
        """Give the controller an arbiter with this fire layer and the real rules."""
        arbiter = build_arbiter(
            [
                *FEATURE_LAYERS,
                LayerRegistration(Layer.FIRE, self.layer, FunctionId.FIRE),
            ]
        )
        controller.engine = Engine(controller.config, arbiter)


def controls(*, dry_run: bool = False, **window_level: Any) -> Controls:
    """Return controls with the given window level (pause, maintenance lock)."""
    return Controls(dry_run=dry_run, window_level=ControlLevel(**window_level))


def collect_reason_events(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return a list that fills with the data of every reason event."""
    fired: list[dict[str, Any]] = []

    @callback
    def _collect(event: Event) -> None:
        fired.append(dict(event.data))

    hass.bus.async_listen(EVENT_REASON, _collect)
    return fired


def state_of(hass: HomeAssistant, entity_id: str) -> State:
    """Return the state of an entity; fail if it has none."""
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state
