"""The button of a window: resume automation.

**Resume automation** (``resume_automation``) ends the manual override of the
window at once (``Engine.resume`` of the core, E2): the automatic movements
no longer wait, the window is recomputed, and nothing is replayed. Without an
override it changes nothing. It sits on the device of the window, next to its
controls, and is available while the window has a controller.
"""

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RollerShutterSuiteConfigEntry
from .entity import WindowStatusEntity

KEY_RESUME = "resume_automation"

RESUME = ButtonEntityDescription(key=KEY_RESUME, translation_key=KEY_RESUME)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RollerShutterSuiteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the button of every window, each to the subentry of its window."""
    del hass
    runtime = entry.runtime_data.runtime
    for window_id in entry.runtime_data.windows:
        async_add_entities(
            [ResumeButton(runtime, window_id, RESUME)], config_subentry_id=window_id
        )


class ResumeButton(WindowStatusEntity, ButtonEntity):
    """Ends the manual override of the window at once."""

    @property
    def available(self) -> bool:
        """Return whether the window has a controller to hand the press to."""
        return self.controller is not None

    async def async_press(self) -> None:
        """End the manual override; the window is recomputed."""
        controller = self.controller
        if controller is not None:
            controller.async_resume()
