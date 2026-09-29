"""The switches of every level: pause and maintenance lock.

The house, every group and every window have both, on their own device
(``entity.ControlEntity``). What each one holds back is decided by the core
from the most restrictive value of the three levels:

- **Pause** (``pause``): holds back comfort movements, such as those of the
  daily routine. Protection and the fire alarm still move the shutter. An
  external pause entity of the same level, if one is set in the form
  "Operation", pauses the level too while it is on or has no value.
- **Maintenance lock** (``maintenance_lock``): nothing moves the shutter, not
  even at a fire alarm; the fire event is still fired. It exists for somebody
  who works on the shutter.

Both are configuration entities. A change recomputes the windows of the level
at once and never reloads the entry.
"""

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RollerShutterSuiteConfigEntry
from .entity import ControlEntity

KEY_PAUSE = "pause"
KEY_MAINTENANCE_LOCK = "maintenance_lock"

PAUSE = SwitchEntityDescription(key=KEY_PAUSE, translation_key=KEY_PAUSE)
MAINTENANCE_LOCK = SwitchEntityDescription(
    key=KEY_MAINTENANCE_LOCK, translation_key=KEY_MAINTENANCE_LOCK
)

_RESTORED_STATES = {STATE_ON: True, STATE_OFF: False}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RollerShutterSuiteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the two switches of the house, of every group and of every window."""
    del hass
    data = entry.runtime_data
    board = data.board
    for level_id, subentry_id in data.control_levels():
        async_add_entities(
            [
                ControlSwitch(data.runtime, board, level_id, PAUSE),
                ControlSwitch(data.runtime, board, level_id, MAINTENANCE_LOCK),
            ],
            config_subentry_id=subentry_id,
        )


class ControlSwitch(ControlEntity, SwitchEntity):
    """The pause or the maintenance lock of one level."""

    entity_description: SwitchEntityDescription

    @property
    def _field(self) -> str:
        return (
            "paused"
            if self.entity_description.key == KEY_PAUSE
            else KEY_MAINTENANCE_LOCK
        )

    @property
    def is_on(self) -> bool:
        """Return whether the level is paused or locked."""
        value: bool = getattr(self.switches, self._field)
        return value

    def stored_value(self) -> bool:
        """Return on or off."""
        return self.is_on

    def restore(self, value: object) -> bool:
        """Take a stored boolean, or the state ``on`` or ``off``."""
        if isinstance(value, str):
            value = _RESTORED_STATES.get(value)
        if not isinstance(value, bool):
            return False
        setattr(self.switches, self._field, value)
        return True

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Pause or lock the level; its windows are recomputed at once."""
        del kwargs
        self._set(value=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """End the pause or the lock of the level; its windows are recomputed."""
        del kwargs
        self._set(value=False)

    def _set(self, *, value: bool) -> None:
        self.board.async_set(self.level_id, **{self._field: value})
        self.async_write_ha_state()
