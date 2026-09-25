"""The sensors of a window: why it is where it is, where it should be, what comes next.

- **Reason** (``active_reason``): an enumeration sensor whose options are the
  reason codes of the core, translated. Its attributes are the decision
  record (``record.decision_attributes``): the layer whose wish won, the
  constraints applied, the answer of the gate, and for every other layer the
  reason why it did not win. For a window in dry-run the record is the
  hypothetical one: ``would_send`` is the position that would have been sent,
  or ``gate_rule`` names the rule that would have held the wish back.
- **Target position** (``target_position``): the common target of the
  members after the constraints; unknown when the window has none (a layer
  holds it where it is, or the members have different targets).
- **Next planned action** (``next_action``): the time of the next change of
  the daily routine, with its target and its reason as attributes. It is
  what the routine will want then, not a promise that the window moves.
"""

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RollerShutterSuiteConfigEntry
from .entity import WindowStatusEntity
from .record import REASON_OPTIONS, active_reason, decision_attributes

KEY_ACTIVE_REASON = "active_reason"
KEY_TARGET_POSITION = "target_position"
KEY_NEXT_ACTION = "next_action"

ACTIVE_REASON = SensorEntityDescription(
    key=KEY_ACTIVE_REASON,
    translation_key=KEY_ACTIVE_REASON,
    device_class=SensorDeviceClass.ENUM,
    options=list(REASON_OPTIONS),
)
TARGET_POSITION = SensorEntityDescription(
    key=KEY_TARGET_POSITION,
    translation_key=KEY_TARGET_POSITION,
    native_unit_of_measurement=PERCENTAGE,
)
NEXT_ACTION = SensorEntityDescription(
    key=KEY_NEXT_ACTION,
    translation_key=KEY_NEXT_ACTION,
    device_class=SensorDeviceClass.TIMESTAMP,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RollerShutterSuiteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the sensors of every window, each to the subentry of its window."""
    del hass
    runtime = entry.runtime_data.runtime
    for window_id in entry.runtime_data.windows:
        async_add_entities(
            [
                ReasonSensor(runtime, window_id, ACTIVE_REASON),
                TargetSensor(runtime, window_id, TARGET_POSITION),
                NextActionSensor(runtime, window_id, NEXT_ACTION),
            ],
            config_subentry_id=window_id,
        )


class ReasonSensor(WindowStatusEntity, SensorEntity):
    """The reason that explains best why the window is where it is."""

    @property
    def native_value(self) -> str | None:
        """Return the reason code of the last decision."""
        status = self.status
        if status is None or status.decision is None:
            return None
        return active_reason(status.decision).value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the decision record, compact and stable."""
        controller = self.controller
        if controller is None or controller.status.decision is None:
            return None
        return decision_attributes(
            controller.status.decision, dry_run=controller.controls().dry_run
        )


class TargetSensor(WindowStatusEntity, SensorEntity):
    """The position the last decision computed for the window."""

    @property
    def native_value(self) -> int | None:
        """Return the common target of the members, if there is one."""
        status = self.status
        if status is None or status.decision is None:
            return None
        target = status.decision.target
        return None if target is None else target.value


class NextActionSensor(WindowStatusEntity, SensorEntity):
    """When the daily routine wants something new next."""

    @property
    def native_value(self) -> datetime | None:
        """Return the time of the next planned action."""
        status = self.status
        if status is None or status.schedule is None:
            return None
        action = status.schedule.next_action
        return None if action is None else action.at

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the target and the reason of the next planned action."""
        status = self.status
        action = (
            None
            if status is None or status.schedule is None
            else status.schedule.next_action
        )
        return {
            "target": None if action is None else action.target.value,
            "reason": None if action is None else action.reason.value,
        }
