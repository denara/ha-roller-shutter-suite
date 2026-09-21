"""Subentry flow of a group: a name and the values its windows share."""

from typing import Any

import probatio
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.helpers.selector import TextSelector

from custom_components.roller_shutter_suite.const import CONF_NAME, CONF_SETTINGS
from custom_components.roller_shutter_suite.core.settings import Level
from custom_components.roller_shutter_suite.features import get_catalog
from custom_components.roller_shutter_suite.stored import (
    level_settings,
    sound_own_values,
)

from .inheritance import as_form_schema
from .model import LevelContext
from .steps import FeatureStepsMixin, install_feature_steps

STEP_BASICS = "basics"


@install_feature_steps
class GroupSubentryFlow(FeatureStepsMixin, ConfigSubentryFlow):
    """Create or change a group.

    basics (name) -> features (switches, if there are any) -> one step per
    feature that is switched on -> save once.
    """

    _name: str

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Start adding a group."""
        return await self.async_step_basics(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Start changing a group."""
        return await self.async_step_basics(user_input)

    async def async_step_basics(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask for the name, which is the title of the subentry."""
        if user_input is not None:
            self._name = user_input[CONF_NAME]
            result: SubentryFlowResult = await self._async_start_feature_steps(
                self._level_context()
            )
            return result

        suggested = (
            {CONF_NAME: self._get_reconfigure_subentry().title}
            if self.source == SOURCE_RECONFIGURE
            else None
        )
        schema = probatio.Schema({probatio.Required(CONF_NAME): TextSelector()})
        return self.async_show_form(
            step_id=STEP_BASICS,
            data_schema=self.add_suggested_values_to_schema(
                as_form_schema(schema), suggested
            ),
        )

    def _level_context(self) -> LevelContext:
        entry = self._get_entry()
        registry = get_catalog().registry
        own = (
            sound_own_values(self._get_reconfigure_subentry().data, registry)
            if self.source == SOURCE_RECONFIGURE
            else {}
        )
        return LevelContext(
            level=Level.GROUP,
            own=own,
            house_title=entry.title,
            house=level_settings(entry.data, registry),
        )

    async def _async_finish(self) -> SubentryFlowResult:
        data = {CONF_SETTINGS: dict(self._context.own)}
        if self.source == SOURCE_RECONFIGURE:
            # The entry has an update listener that schedules the reload, so
            # the flow only updates; a reloading method would raise here.
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                title=self._name,
                data=data,
            )
        return self.async_create_entry(title=self._name, data=data)
