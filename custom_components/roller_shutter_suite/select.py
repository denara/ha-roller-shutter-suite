"""The operating mode of every level.

The house, every group and every window have one, on their own device
(``entity.ControlEntity``). The options are the operating modes of the core:

| Option | Comfort | Protection | Fire alarm |
|---|---|---|---|
| automatic | moves | moves | opens |
| protection only | held back | moves | opens |
| off | held back | held back | opens |

The mode in effect for a window is the most restrictive of the house, its
group and the window. A configuration entity; a change recomputes the windows
of the level at once and never reloads the entry.
"""

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RollerShutterSuiteConfigEntry
from .core.model import OperatingMode
from .entity import ControlEntity

KEY_OPERATING_MODE = "operating_mode"
MODES = [mode.value for mode in OperatingMode]

OPERATING_MODE = SelectEntityDescription(
    key=KEY_OPERATING_MODE,
    translation_key=KEY_OPERATING_MODE,
    options=MODES,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RollerShutterSuiteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the operating mode of the house, of every group and of every window."""
    del hass
    data = entry.runtime_data
    for level_id, subentry_id in data.control_levels():
        async_add_entities(
            [OperatingModeSelect(data.runtime, data.board, level_id, OPERATING_MODE)],
            config_subentry_id=subentry_id,
        )


class OperatingModeSelect(ControlEntity, SelectEntity):
    """The operating mode of one level."""

    @property
    def current_option(self) -> str:
        """Return the mode the level is set to."""
        return self.switches.mode.value

    def stored_value(self) -> str:
        """Return the mode."""
        return self.current_option

    def restore(self, value: object) -> bool:
        """Take a stored mode; anything else is not one."""
        if not isinstance(value, str) or value not in MODES:
            return False
        self.switches.mode = OperatingMode(value)
        return True

    async def async_select_option(self, option: str) -> None:
        """Set the mode of the level; its windows are recomputed at once."""
        self.board.async_set(self.level_id, mode=OperatingMode(option))
        self.async_write_ha_state()
