"""Config flow of the Roller Shutter Suite integration (SPIKE S2)."""

from typing import Any, override

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
)
from homeassistant.core import callback

from .const import (
    CONF_SETTINGS,
    DOMAIN,
    ENTRY_TITLE,
    SUBENTRY_GROUP,
    SUBENTRY_PATTERN_LAB,
    SUBENTRY_WINDOW,
)
from .features import FEATURES
from .flow.group_flow import GroupSubentryFlow
from .flow.model import LevelContext, SettingValue
from .flow.pattern_lab import PatternLabSubentryFlow
from .flow.steps import FeatureStepsMixin, install_feature_steps
from .flow.window_flow import WindowSubentryFlow


def default_settings() -> dict[str, SettingValue]:
    """Return the house-level defaults of every registered feature."""
    settings: dict[str, SettingValue] = {}
    for feature in FEATURES:
        settings[feature.switch.key] = feature.switch.default
        settings.update({setting.key: setting.default for setting in feature.fields})
    return settings


@install_feature_steps
class RollerShutterSuiteConfigFlow(FeatureStepsMixin, ConfigFlow, domain=DOMAIN):
    """Create the single config entry, and reconfigure the house-level values."""

    VERSION = 1
    MINOR_VERSION = 1

    @classmethod
    @callback
    @override
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentry types: groups, windows and the spike's lab."""
        return {
            SUBENTRY_GROUP: GroupSubentryFlow,
            SUBENTRY_WINDOW: WindowSubentryFlow,
            SUBENTRY_PATTERN_LAB: PatternLabSubentryFlow,
        }

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for confirmation, then create the entry with the defaults."""
        if user_input is not None:
            return self.async_create_entry(
                title=ENTRY_TITLE, data={CONF_SETTINGS: default_settings()}
            )

        return self.async_show_form(step_id="user")

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the house-level values; there is no options flow."""
        entry = self._get_reconfigure_entry()
        self._start_feature_steps(
            LevelContext(
                own=default_settings() | dict(entry.data.get(CONF_SETTINGS, {})),
                parents=(),
            )
        )
        result: ConfigFlowResult = await self.async_step_features()
        return result

    async def _async_finish(self) -> ConfigFlowResult:
        # The entry has an update listener, so: update and abort, no reload here.
        return self.async_update_and_abort(
            self._get_reconfigure_entry(),
            data_updates={CONF_SETTINGS: dict(self._level.own)},
        )
