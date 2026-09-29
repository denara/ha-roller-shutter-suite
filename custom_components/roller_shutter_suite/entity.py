"""The base of the status entities of a window, and of the controls of every level.

Every status entity belongs to the device of its window and to the window's
subentry. It never polls: the controller of the window sends a signal after
every recompute (``const.status_signal``), and the entity reads the status
then. It is unavailable while the window has no controller, before the first
observation of its covers, and while none of its covers is available; it
comes back with the first recompute that sees a cover again, without a
reload.

The controls (pause, maintenance lock, operating mode) are the entities of
:class:`ControlEntity`, on the device of the house, of a group or of a window.
"""

from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Final

from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity

from .const import DOMAIN, status_signal
from .controller import WindowController, WindowStatus
from .controls import ControlBoard, LevelSwitches
from .core.settings import Level
from .runtime import SuiteRuntime

RESTORED_VALUE: Final = "value"
"""The key of the value in the extra data a control stores for its restore."""


@dataclass(frozen=True, slots=True)
class ControlValue(ExtraStoredData):
    """The value of a control as it is stored for the next start."""

    value: bool | str

    def as_dict(self) -> dict[str, Any]:
        """Return the value as a dictionary for the restore state storage."""
        return {RESTORED_VALUE: self.value}


class WindowStatusEntity(Entity):
    """An entity that shows part of the status of one window."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, runtime: SuiteRuntime, window_id: str, description: EntityDescription
    ) -> None:
        """Create the entity of one window.

        It looks the controller up in the runtime every time, so a controller
        that was replaced is never read.
        """
        self.runtime = runtime
        self.window_id = window_id
        self.entity_description = description
        self._attr_unique_id = f"{window_id}_{description.key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, window_id)})

    @property
    def controller(self) -> WindowController | None:
        """Return the controller the window has now, if any."""
        return self.runtime.windows.get(self.window_id)

    @property
    def status(self) -> WindowStatus | None:
        """Return the status of the window, if it has a controller."""
        controller = self.controller
        return None if controller is None else controller.status

    @property
    def available(self) -> bool:
        """Return whether at least one cover of the window is available."""
        status = self.status
        return (
            status is not None
            and status.observation is not None
            and status.observation.available
        )

    async def async_added_to_hass(self) -> None:
        """Follow the status of the window."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, status_signal(self.window_id), self._on_status
            )
        )

    @callback
    def _on_status(self) -> None:
        self.async_write_ha_state()


class ControlEntity(RestoreEntity):
    """A control of one level: the house, a group or a window.

    It belongs to the device of its level: the house device of the entry, the
    device of a group's subentry, or the device of a window. Its value lives
    in the :class:`~.controls.ControlBoard` of the entry while the entry is
    loaded, and it survives a reload and a restart as entity state
    (``RestoreEntity``): the value is stored as extra data, so it is restored
    also when the entity was unavailable when Home Assistant stopped. Without
    a stored value the control keeps its default (off, or automatic).

    A control of a window is unavailable while the window has no controller,
    as every entity of a window; the controls of the house and of a group are
    always available. A change never reloads the entry.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        runtime: SuiteRuntime,
        board: ControlBoard,
        level_id: str,
        description: EntityDescription,
    ) -> None:
        """Create the control of one level."""
        self.runtime = runtime
        self.board = board
        self.level_id = level_id
        self.entity_description = description
        self._attr_unique_id = f"{level_id}_{description.key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, level_id)})

    @property
    def switches(self) -> LevelSwitches:
        """Return what the controls of the level say now."""
        return self.board.switches[self.level_id]

    @property
    def available(self) -> bool:
        """Return whether the level can be controlled: a window needs its controller."""
        if self.board.level_kind(self.level_id) is not Level.WINDOW:
            return True
        return self.level_id in self.runtime.windows

    @property
    def extra_restore_state_data(self) -> ControlValue:
        """Return the value to restore, whatever the state is at the moment."""
        return ControlValue(self.stored_value())

    @abstractmethod
    def stored_value(self) -> bool | str:
        """Return the value of the control in its stored form."""

    @abstractmethod
    def restore(self, value: object) -> bool:
        """Take a restored value; return whether it was one this control can hold."""

    async def async_added_to_hass(self) -> None:
        """Restore the value, then follow the controller of a window."""
        await super().async_added_to_hass()
        extra = await self.async_get_last_extra_data()
        restored = False
        if extra is not None:
            restored = self.restore(extra.as_dict().get(RESTORED_VALUE))
        if not restored and (state := await self.async_get_last_state()) is not None:
            self.restore(state.state)
        if self.board.level_kind(self.level_id) is Level.WINDOW:
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass, status_signal(self.level_id), self._on_status
                )
            )

    @callback
    def _on_status(self) -> None:
        self.async_write_ha_state()
