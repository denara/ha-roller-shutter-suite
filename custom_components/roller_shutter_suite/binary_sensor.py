"""The binary sensors of a window: manual override and dry-run.

- **Manual override** (``override_active``): on while a movement by hand holds
  the automatic comfort movements back: while the manual override dam of the
  window is armed. In dry-run it is never armed, so the sensor stays off.
- **Dry-run** (``dry_run``): on while the window decides and records but
  moves nothing. A diagnostic entity: it is changed in the settings of the
  window, not here.
"""

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RollerShutterSuiteConfigEntry
from .entity import WindowStatusEntity

KEY_OVERRIDE_ACTIVE = "override_active"
KEY_DRY_RUN = "dry_run"

OVERRIDE_ACTIVE = BinarySensorEntityDescription(
    key=KEY_OVERRIDE_ACTIVE, translation_key=KEY_OVERRIDE_ACTIVE
)
DRY_RUN = BinarySensorEntityDescription(
    key=KEY_DRY_RUN,
    translation_key=KEY_DRY_RUN,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RollerShutterSuiteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the binary sensors of every window, each to the subentry of its window."""
    del hass
    runtime = entry.runtime_data.runtime
    for window_id in entry.runtime_data.windows:
        async_add_entities(
            [
                OverrideSensor(runtime, window_id, OVERRIDE_ACTIVE),
                DryRunSensor(runtime, window_id, DRY_RUN),
            ],
            config_subentry_id=window_id,
        )


class OverrideSensor(WindowStatusEntity, BinarySensorEntity):
    """Whether a manual override holds the window: it follows the dam."""

    @property
    def is_on(self) -> bool | None:
        """Return whether the manual override dam of the window is armed."""
        controller = self.controller
        return (
            None if controller is None else controller.state.manual_override is not None
        )


class DryRunSensor(WindowStatusEntity, BinarySensorEntity):
    """Whether the window is in dry-run."""

    @property
    def is_on(self) -> bool | None:
        """Return whether the window decides without moving."""
        controller = self.controller
        return None if controller is None else controller.controls().dry_run
