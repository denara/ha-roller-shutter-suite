"""SPIKE S2: subentry flow of a group (shared defaults for windows)."""

from typing import Any

import probatio
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.helpers.selector import TextSelector

from custom_components.roller_shutter_suite.const import CONF_NAME, CONF_SETTINGS

from .inheritance import as_form_schema
from .model import LevelContext, Parent
from .steps import FeatureStepsMixin, install_feature_steps


@install_feature_steps
class GroupSubentryFlow(FeatureStepsMixin, ConfigSubentryFlow):
    """Create or change a group: name, feature switches, feature steps."""

    _name: str

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Start adding a group."""
        self._start_feature_steps(LevelContext(own={}, parents=self._parents()))
        return await self.async_step_basics(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Start changing a group."""
        subentry = self._get_reconfigure_subentry()
        self._start_feature_steps(
            LevelContext(
                own=dict(subentry.data.get(CONF_SETTINGS, {})),
                parents=self._parents(),
            )
        )
        return await self.async_step_basics(user_input)

    async def async_step_basics(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask for the name."""
        if user_input is not None:
            self._name = user_input[CONF_NAME]
            result: SubentryFlowResult = await self.async_step_features()
            return result

        suggested = (
            {CONF_NAME: self._get_reconfigure_subentry().title}
            if self.source == SOURCE_RECONFIGURE
            else None
        )
        schema = probatio.Schema({probatio.Required(CONF_NAME): TextSelector()})
        return self.async_show_form(
            step_id="basics",
            data_schema=self.add_suggested_values_to_schema(
                as_form_schema(schema), suggested
            ),
        )

    def _parents(self) -> tuple[Parent, ...]:
        entry = self._get_entry()
        return (Parent(entry.title, entry.data.get(CONF_SETTINGS, {})),)

    async def _async_finish(self) -> SubentryFlowResult:
        data = {CONF_SETTINGS: dict(self._level.own)}
        if self.source == SOURCE_RECONFIGURE:
            # The entry has an update listener that reloads it, so the flow
            # must not reload as well: update and abort, nothing else.
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                title=self._name,
                data=data,
            )
        return self.async_create_entry(title=self._name, data=data)
