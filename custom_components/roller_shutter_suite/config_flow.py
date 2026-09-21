"""Config flow of the house: the single config entry and its values.

The values of the house are changed through a reconfigure flow; there is no
options flow. The flows of groups and windows are subentry flows and live in
the ``flow`` package.
"""

from typing import Any, override

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
)
from homeassistant.core import callback

from .const import (
    CONF_SETTINGS,
    CONFIG_MINOR_VERSION,
    CONFIG_VERSION,
    DOMAIN,
    ENTRY_TITLE,
    SUBENTRY_GROUP,
    SUBENTRY_WINDOW,
)
from .core.settings import Level
from .features import get_catalog
from .flow.group_flow import GroupSubentryFlow
from .flow.model import LevelContext
from .flow.steps import FeatureStepsMixin, install_feature_steps
from .flow.window_flow import WindowSubentryFlow
from .stored import sound_own_values


@install_feature_steps
class RollerShutterSuiteConfigFlow(FeatureStepsMixin, ConfigFlow, domain=DOMAIN):
    """Create the single config entry, and change the values of the house.

    user (confirmation) or reconfigure -> features (switches, if there are
    any) -> one step per feature that is switched on -> save once. A second
    entry is refused by Home Assistant itself, because the manifest sets
    ``single_config_entry``.
    """

    VERSION = CONFIG_VERSION
    MINOR_VERSION = CONFIG_MINOR_VERSION

    @classmethod
    @callback
    @override
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentry types: groups and windows."""
        return {SUBENTRY_GROUP: GroupSubentryFlow, SUBENTRY_WINDOW: WindowSubentryFlow}

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for confirmation, then for the values of the house."""
        if user_input is None:
            return self.async_show_form(step_id="user")
        result: ConfigFlowResult = await self._async_start_feature_steps(
            LevelContext(level=Level.GLOBAL, own={}, house_title=ENTRY_TITLE)
        )
        return result

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the values of the house."""
        entry = self._get_reconfigure_entry()
        result: ConfigFlowResult = await self._async_start_feature_steps(
            LevelContext(
                level=Level.GLOBAL,
                own=sound_own_values(entry.data, get_catalog().registry),
                house_title=entry.title,
            )
        )
        return result

    async def _async_finish(self) -> ConfigFlowResult:
        data = {CONF_SETTINGS: dict(self._context.own)}
        if self.source == SOURCE_RECONFIGURE:
            # The entry has an update listener that schedules the reload, so
            # the flow only updates; a reloading method would log a usage
            # report and become an error in Home Assistant 2026.12.
            return self.async_update_and_abort(
                self._get_reconfigure_entry(), data_updates=data
            )
        return self.async_create_entry(title=ENTRY_TITLE, data=data)
