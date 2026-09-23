"""The runtime of the config entry: one window controller per window.

It owns the controllers and the ports they share (clock, sun, storage,
actuator). Windows are added, reloaded and removed one by one; what happens
to one of them never touches the listeners and timers of the others, and a
window whose controller cannot be created is logged once with its name and
left out while every other window runs. Nothing here raises for a single
window; the config entry is loaded as long as Home Assistant itself is.

The controls of a window (pause, operating mode, maintenance lock on three
levels, and dry-run) are read through ``controls_of``; until the block that
builds the switches exists, the three levels are neutral and dry-run is what
the window's subentry says.
"""

import logging
from collections.abc import Callable, Mapping

from homeassistant.core import HomeAssistant, callback

from .controller import WindowController
from .core.model import Controls
from .core.ports import Actuator, Clock, Storage, Sun
from .windows import WindowRuntime

_LOGGER = logging.getLogger(__name__)

CONFIGURATION_WITHHELD = "configuration_withheld"
"""Why a window has no controller: the resolver withheld its configuration."""

type ControlsProvider = Callable[[WindowRuntime], Controls]


def neutral_controls(window: WindowRuntime) -> Controls:
    """Return the controls of a window while nothing can be switched yet."""
    return Controls(dry_run=window.dry_run)


class SuiteRuntime:
    """The controllers of the windows of the config entry."""

    def __init__(  # noqa: PLR0913 - the ports of the core are the input
        self,
        hass: HomeAssistant,
        *,
        clock: Clock,
        sun: Sun,
        storage: Storage,
        actuator: Actuator,
        controls_of: ControlsProvider = neutral_controls,
    ) -> None:
        """Create the runtime with the ports every controller shares."""
        self.hass = hass
        self.clock = clock
        self.sun = sun
        self.storage = storage
        self.actuator = actuator
        self.controls_of = controls_of
        self.windows: dict[str, WindowController] = {}
        self.failed: dict[str, str] = {}
        """The windows without a controller, by subentry ID, with the reason:
        the type of the exception, or ``configuration_withheld``."""

    @callback
    def async_start(self, windows: Mapping[str, WindowRuntime]) -> None:
        """Set every window up; a window that fails is logged and left out."""
        for window in windows.values():
            self.async_add_window(window)

    @callback
    def async_add_window(self, window: WindowRuntime) -> bool:
        """Create and start the controller of one window; say whether it runs."""
        self.failed.pop(window.subentry_id, None)
        config = window.resolution.config
        if config is None:
            _LOGGER.error(
                "Window %s has no configuration and is not controlled", window.title
            )
            self.failed[window.subentry_id] = CONFIGURATION_WITHHELD
            return False
        controller: WindowController | None = None
        try:
            controller = WindowController(
                self.hass,
                window_id=window.subentry_id,
                title=window.title,
                config=config,
                clock=self.clock,
                sun=self.sun,
                storage=self.storage,
                actuator=self.actuator,
                controls=lambda: self.controls_of(window),
            )
            controller.async_start()
        except Exception as error:
            # A programming error: the traceback belongs in the log; the
            # message line names only the type of the exception.
            _LOGGER.exception(
                "Window %s could not be set up (%s) and is not controlled; the "
                "other windows run",
                window.title,
                type(error).__name__,
            )
            self.failed[window.subentry_id] = type(error).__name__
            if controller is not None:
                # Whatever the start registered before it raised is released.
                controller.async_stop()
            return False
        self.windows[window.subentry_id] = controller
        return True

    @callback
    def async_remove_window(self, window_id: str) -> None:
        """Stop and forget the controller of one window, if it has one."""
        self.failed.pop(window_id, None)
        controller = self.windows.pop(window_id, None)
        if controller is not None:
            controller.async_stop()

    @callback
    def async_reload_window(self, window: WindowRuntime) -> bool:
        """Replace the controller of one window with a fresh one."""
        self.async_remove_window(window.subentry_id)
        return self.async_add_window(window)

    @callback
    def async_stop(self) -> None:
        """Stop every controller; no listener and no timer remains."""
        for window_id in list(self.windows):
            self.async_remove_window(window_id)
