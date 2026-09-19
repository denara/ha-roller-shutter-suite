"""Config flow of the Roller Shutter Suite integration."""

from typing import Any, override

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN, ENTRY_TITLE


class RollerShutterSuiteConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the single config entry that represents the house.

    A second entry is refused by Home Assistant itself, because the manifest
    sets ``single_config_entry``. The flow has no fields, so it needs no schema.
    """

    VERSION = 1
    MINOR_VERSION = 1

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for confirmation, then create the entry."""
        if user_input is not None:
            return self.async_create_entry(title=ENTRY_TITLE, data={})

        return self.async_show_form(step_id="user")
