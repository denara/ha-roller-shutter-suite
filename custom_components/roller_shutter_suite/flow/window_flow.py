"""Subentry flow of a window: its covers, its group, and what it sets itself."""

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

from custom_components.roller_shutter_suite.capabilities import member_configs
from custom_components.roller_shutter_suite.const import (
    CONF_COVERS,
    CONF_DRY_RUN,
    CONF_GROUP_ID,
    CONF_NAME,
    CONF_SETTINGS,
    SUBENTRY_GROUP,
)
from custom_components.roller_shutter_suite.core.model import (
    CapabilityState,
    MemberConfig,
)
from custom_components.roller_shutter_suite.core.settings import Level
from custom_components.roller_shutter_suite.features import get_catalog
from custom_components.roller_shutter_suite.stored import (
    COVER_DOMAIN,
    level_settings,
    read_window_identity,
    sound_own_values,
)

from .covers import ResolvedCovers, find_conflict, resolve_covers
from .inheritance import as_form_schema
from .model import GroupParent, LevelContext
from .steps import FeatureStepsMixin, install_feature_steps

STEP_BASICS = "basics"
STEP_MEMBERS = "members"
STEP_MEMBERS_ACCEPT = "members_accept"
STEP_DEGRADED = "degraded"
STEP_DEGRADED_ACCEPT = "degraded_accept"

ERROR_NO_COVERS = "no_covers"
ERROR_COVER_IN_USE = "cover_in_use"
ERROR_NAME_BLANK = "name_blank"
ERROR_GROUP_REMOVED = "group_removed"
ABORT_SUBENTRY_REMOVED = "subentry_removed"


def _without_position(members: tuple[MemberConfig, ...]) -> list[str]:
    """Return the members that definitely cannot be driven to, or report, a position.

    Decided by the capability state: a member about which nothing is known is
    not listed, because nothing is concluded from it.
    """
    return [
        member.member_id
        for member in members
        if CapabilityState.MISSING
        in (
            member.capabilities.capability_state("supports_set_position"),
            member.capabilities.capability_state("reports_position"),
        )
    ]


@install_feature_steps
class WindowSubentryFlow(FeatureStepsMixin, ConfigSubentryFlow):
    """Create or change a window.

    basics (name, covers, group) -> members (only if a cover group was taken
    apart) -> degraded (only if a cover works without positions) -> features
    (switches, if there are any) -> one step per feature that is switched on
    -> save once.
    """

    _name: str
    _group_id: str | None
    _resolved: ResolvedCovers
    _members: tuple[MemberConfig, ...]
    _last_basics: dict[str, Any] | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Start adding a window."""
        return await self.async_step_basics(user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Start changing a window."""
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

    def _own_subentry_is_gone(self) -> bool:
        """Return whether the window that is changed was removed while the flow was open."""
        return (
            self.source == SOURCE_RECONFIGURE
            and self._reconfigure_subentry_id not in self._get_entry().subentries
        )

    def _group_is_gone(self) -> bool:
        """Return whether the chosen group was removed while the flow was open."""
        return self._group_id is not None and self._group_id not in self._groups()

    def _show_group_removed(self) -> SubentryFlowResult:
        """Go back to the first page, which no longer offers the group, and say why.

        Home Assistant removes a subentry without asking, also while a flow is
        open that refers to it. The flow goes on as the set-up does for a group
        that is gone: the window inherits from the house unless the user
        chooses another group, and no reference to the removed group is stored.
        """
        self._group_id = None
        self._last_basics = {
            key: value
            for key, value in (self._last_basics or {}).items()
            if key != CONF_GROUP_ID
        }
        return self._show_basics({"base": ERROR_GROUP_REMOVED})

    def _conflict(self) -> tuple[str, str] | None:
        return find_conflict(
            self._get_entry(), self._resolved.members, self._own_subentry_id()
        )

    async def async_step_basics(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask for name, covers and group; refuse covers of another window."""
        if user_input is None:
            return self._show_basics()
        if self._own_subentry_is_gone():
            return self.async_abort(reason=ABORT_SUBENTRY_REMOVED)
        if (refusal := self._refuse_basics(user_input)) is not None:
            return refusal
        if self._resolved.groups:
            return await self.async_step_members()
        return await self.async_step_degraded()

    def _refuse_basics(self, user_input: dict[str, Any]) -> SubentryFlowResult | None:
        """Take the input of the first page; return the page again if it is refused."""
        self._last_basics = user_input
        self._name = user_input[CONF_NAME].strip()
        if not self._name:
            return self._show_basics({CONF_NAME: ERROR_NAME_BLANK})
        self._resolved = resolve_covers(self.hass, user_input[CONF_COVERS])
        if not self._resolved.members:
            return self._show_basics({CONF_COVERS: ERROR_NO_COVERS})
        if (conflict := self._conflict()) is not None:
            return self._show_cover_in_use(conflict)
        self._group_id = user_input.get(CONF_GROUP_ID)
        if self._group_is_gone():
            return self._show_group_removed()
        return None

    def _show_cover_in_use(self, conflict: tuple[str, str]) -> SubentryFlowResult:
        return self._show_basics(
            {CONF_COVERS: ERROR_COVER_IN_USE},
            {"cover": conflict[0], "window": conflict[1]},
        )

    def _show_basics(
        self,
        errors: dict[str, str] | None = None,
        placeholders: dict[str, str] | None = None,
    ) -> SubentryFlowResult:
        schema: dict[probatio.Marker, Any] = {
            probatio.Required(CONF_NAME): TextSelector(),
            probatio.Required(CONF_COVERS): EntitySelector(
                EntitySelectorConfig(domain=COVER_DOMAIN, multiple=True)
            ),
        }
        groups = self._groups()
        if groups:
            # Optional and without a default: an emptied field sends no key,
            # and an absent key is the only way to say "no group".
            schema[probatio.Optional(CONF_GROUP_ID)] = SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value=group_id, label=title)
                        for group_id, title in groups.items()
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            )

        suggested = self._last_basics
        if suggested is None and self.source == SOURCE_RECONFIGURE:
            subentry = self._get_reconfigure_subentry()
            identity = read_window_identity(subentry.data)
            suggested = {
                CONF_NAME: subentry.title,
                CONF_COVERS: list(identity.covers or ()),
            }
            # A reference to a group that no longer exists is not suggested,
            # so saving the form repairs it.
            if identity.group_id in groups:
                suggested[CONF_GROUP_ID] = identity.group_id
        return self.async_show_form(
            step_id=STEP_BASICS,
            data_schema=self.add_suggested_values_to_schema(
                as_form_schema(probatio.Schema(schema)), suggested
            ),
            errors=errors,
            description_placeholders=placeholders,
        )

    async def async_step_members(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Show what a cover group was taken apart into, before anything is saved.

        A menu, because flows have no "back" button: the second entry is the
        way back to the selection.
        """
        return self.async_show_menu(
            step_id=STEP_MEMBERS,
            menu_options=[STEP_MEMBERS_ACCEPT, STEP_BASICS],
            description_placeholders={
                "groups": ", ".join(self._resolved.groups),
                "members": ", ".join(self._resolved.members),
            },
        )

    async def async_step_members_accept(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Continue with the covers the selection was taken apart into."""
        return await self.async_step_degraded()

    async def async_step_degraded(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Read what the members can do; explain a cover that works without positions.

        Such a cover is accepted (N2). The page says what is inactive for it,
        and like the page of the members it offers the way back.
        """
        self._members = member_configs(self.hass, tuple(self._resolved.members))
        if degraded := _without_position(self._members):
            return self.async_show_menu(
                step_id=STEP_DEGRADED,
                menu_options=[STEP_DEGRADED_ACCEPT, STEP_BASICS],
                description_placeholders={"covers": ", ".join(degraded)},
            )
        return await self.async_step_degraded_accept()

    async def async_step_degraded_accept(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Continue with the feature steps of the window."""
        result: SubentryFlowResult = await self._async_start_feature_steps(
            self._level_context()
        )
        return result

    def _level_context(self) -> LevelContext:
        entry = self._get_entry()
        registry = get_catalog().registry
        own = (
            sound_own_values(self._get_reconfigure_subentry().data, registry)
            if self.source == SOURCE_RECONFIGURE
            else {}
        )
        group: GroupParent | None = None
        # The first page has just checked that the group still exists.
        subentry = entry.subentries.get(self._group_id or "")
        if subentry is not None:
            group = GroupParent(
                group_id=subentry.subentry_id,
                title=subentry.title,
                settings=level_settings(subentry.data, registry),
            )
        return LevelContext(
            level=Level.WINDOW,
            own=own,
            house_title=entry.title,
            house=level_settings(entry.data, registry),
            group=group,
            members=self._members,
        )

    async def _async_finish(self) -> SubentryFlowResult:
        # The flow was open for a while. What it took from the first page is
        # checked again right before saving: the window itself and its group
        # may have been removed, and another flow may have taken a cover.
        if self._own_subentry_is_gone():
            return self.async_abort(reason=ABORT_SUBENTRY_REMOVED)
        if (conflict := self._conflict()) is not None:
            return self._show_cover_in_use(conflict)
        if self._group_is_gone():
            return self._show_group_removed()
        data: dict[str, Any] = {
            CONF_COVERS: list(self._resolved.members),
            CONF_SETTINGS: dict(self._context.own),
        }
        if self._group_id is not None:
            data[CONF_GROUP_ID] = self._group_id
        if self.source == SOURCE_RECONFIGURE:
            subentry = self._get_reconfigure_subentry()
            data[CONF_DRY_RUN] = read_window_identity(subentry.data).dry_run
            return self.async_update_and_abort(
                self._get_entry(), subentry, title=self._name, data=data
            )
        # New windows start in dry-run (architecture document, decision 12).
        data[CONF_DRY_RUN] = True
        return self.async_create_entry(title=self._name, data=data)
