"""SPIKE S2: subentry flow of a window."""

from typing import Any

import probatio
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from custom_components.roller_shutter_suite.const import (
    CONF_COVERS,
    CONF_DRY_RUN,
    CONF_GROUP_ID,
    CONF_NAME,
    CONF_SETTINGS,
    SUBENTRY_GROUP,
)

from .covers import (
    COVER_DOMAIN,
    ResolvedCovers,
    detect_capabilities,
    find_conflict,
    resolve_covers,
)
from .inheritance import as_form_schema
from .model import LevelContext, Parent
from .steps import FeatureStepsMixin, install_feature_steps


@install_feature_steps
class WindowSubentryFlow(FeatureStepsMixin, ConfigSubentryFlow):
    """Create or change a window.

    basics (name, covers, group) -> members (only if a cover group was taken
    apart) -> features (switches) -> one step per enabled feature -> save.
    """

    _name: str
    _group_id: str | None
    _resolved: ResolvedCovers
    _own_settings: dict[str, Any]
    _last_basics: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Start adding a window."""
        self._own_settings = {}
        return await self.async_step_basics(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Start changing a window."""
        self._own_settings = dict(
            self._get_reconfigure_subentry().data.get(CONF_SETTINGS, {})
        )
        return await self.async_step_basics(user_input)

    def _own_subentry_id(self) -> str | None:
        if self.source == SOURCE_RECONFIGURE:
            return self._get_reconfigure_subentry().subentry_id
        return None

    def _groups(self) -> dict[str, str]:
        return {
            subentry.subentry_id: subentry.title
            for subentry in self._get_entry().subentries.values()
            if subentry.subentry_type == SUBENTRY_GROUP
        }

    async def async_step_basics(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask for name, covers and group; refuse covers of another window."""
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if user_input is not None:
            self._last_basics = user_input
            resolved = resolve_covers(self.hass, user_input[CONF_COVERS])
            conflict = find_conflict(
                self._get_entry(), resolved.members, self._own_subentry_id()
            )
            if not resolved.members:
                errors[CONF_COVERS] = "no_covers"
            elif conflict is not None:
                errors[CONF_COVERS] = "cover_in_use"
                placeholders = {"cover": conflict[0], "window": conflict[1]}
            else:
                self._name = user_input[CONF_NAME]
                self._group_id = user_input.get(CONF_GROUP_ID)
                self._resolved = resolved
                if resolved.groups:
                    return await self.async_step_members()
                return await self.async_step_members_accept()

        schema: dict[probatio.Marker, Any] = {
            probatio.Required(CONF_NAME): TextSelector(),
            probatio.Required(CONF_COVERS): EntitySelector(
                EntitySelectorConfig(domain=COVER_DOMAIN, multiple=True)
            ),
        }
        if groups := self._groups():
            # Optional and without default: an empty field means "no group".
            schema[probatio.Optional(CONF_GROUP_ID)] = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=group_id, label=title)
                        for group_id, title in groups.items()
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )

        suggested: dict[str, Any] | None = user_input or self._last_basics
        if suggested is None and self.source == SOURCE_RECONFIGURE:
            subentry = self._get_reconfigure_subentry()
            suggested = {
                CONF_NAME: subentry.title,
                CONF_COVERS: subentry.data[CONF_COVERS],
            }
            # A reference to a group that no longer exists is not suggested,
            # so saving the form repairs it.
            if subentry.data.get(CONF_GROUP_ID) in groups:
                suggested[CONF_GROUP_ID] = subentry.data[CONF_GROUP_ID]
        return self.async_show_form(
            step_id="basics",
            data_schema=self.add_suggested_values_to_schema(
                as_form_schema(probatio.Schema(schema)), suggested
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_members(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Show what a cover group was resolved into before anything is saved.

        A menu, because flows have no "back" button: the second entry is the
        way back to the selection.
        """
        return self.async_show_menu(
            step_id="members",
            menu_options=["members_accept", "basics"],
            description_placeholders={
                "groups": ", ".join(self._resolved.groups),
                "members": ", ".join(self._resolved.members),
            },
        )

    async def async_step_members_accept(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Continue with the resolved members."""
        capabilities = detect_capabilities(self.hass, self._resolved.members)
        entry = self._get_entry()
        parents = [Parent(entry.title, entry.data.get(CONF_SETTINGS, {}))]
        if self._group_id is not None:
            group = entry.subentries[self._group_id]
            parents.insert(0, Parent(group.title, group.data.get(CONF_SETTINGS, {})))
        self._start_feature_steps(
            LevelContext(
                own=self._own_settings,
                parents=tuple(parents),
                capabilities=capabilities.supported,
                placeholders={
                    f"limited_by_{capability}": member
                    for capability, member in capabilities.limited_by.items()
                },
            )
        )
        result: SubentryFlowResult = await self.async_step_features()
        return result

    async def _async_finish(self) -> SubentryFlowResult:
        data = {
            CONF_COVERS: self._resolved.members,
            CONF_GROUP_ID: self._group_id,
            CONF_SETTINGS: dict(self._level.own),
        }
        if self.source == SOURCE_RECONFIGURE:
            subentry = self._get_reconfigure_subentry()
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=self._name,
                data=data | {CONF_DRY_RUN: subentry.data.get(CONF_DRY_RUN, True)},
            )
        # New windows start in dry-run (architecture document, section 13).
        return self.async_create_entry(
            title=self._name, data=data | {CONF_DRY_RUN: True}
        )
