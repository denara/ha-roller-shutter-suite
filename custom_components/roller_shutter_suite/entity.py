"""The base of the status entities of a window.

Every status entity belongs to the device of its window and to the window's
subentry. It never polls: the controller of the window sends a signal after
every recompute (``const.status_signal``), and the entity reads the status
then. It is unavailable while the window has no controller, before the first
observation of its covers, and while none of its covers is available; it
comes back with the first recompute that sees a cover again, without a
reload.
"""

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity, EntityDescription

from .const import DOMAIN, status_signal
from .controller import WindowController, WindowStatus
from .runtime import SuiteRuntime


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
