"""Subentry flow of a window: its covers, its group, what it sets itself, and arming.

A new window always starts in dry-run. Its reconfigure flow ends with the
page "dry-run or armed" (E11); the step from dry-run to armed leads to a page
of its own that repeats the checks of the pilot guide and saves only when
every one is confirmed. Going back to dry-run needs no confirmation. Saving
reloads the entry as every change does; the controller then starts the armed
window with a clean state (``Engine.arm``).

After the feature pages every cover of the window gets a page of its own
(``flow/member_page.py``): what no entity can report about it.

Facts refuse arming whatever is ticked: a cover whose reporting kind or time
is not stated on its page, or which is polled, because a movement by hand
between two polls would be undone (rulings of the project owner, 2026-09-29
and 2026-10-01, until block H15 verifies commands); a known reporting time
above zero does not refuse. The guard of maintenance item X10
(``const.MOVEMENT_DETECTION_WIRED``, true since block H10) is the other. While
a fact holds, no path writes ``dry_run: false``: keeping an armed window armed
leads to the same page and is refused as well, and going back to dry-run
always works.
"""

from typing import Any, Final

import probatio
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from custom_components.roller_shutter_suite import const
from custom_components.roller_shutter_suite.capabilities import (
    member_configs,
    reporting_facts,
    with_stated,
)
from custom_components.roller_shutter_suite.const import (
    CONF_COVERS,
    CONF_DRY_RUN,
    CONF_GROUP_ID,
    CONF_MEMBERS,
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
    sound_member_values,
    sound_own_values,
)

from . import member_page
from .covers import ResolvedCovers, find_conflict, resolve_covers
from .inheritance import as_form_schema
from .model import GroupParent, LevelContext
from .steps import FeatureStepsMixin, install_feature_steps

STEP_BASICS = "basics"
STEP_MEMBERS = "members"
STEP_MEMBERS_ACCEPT = "members_accept"
STEP_DEGRADED = "degraded"
STEP_DEGRADED_ACCEPT = "degraded_accept"

STEP_OPERATION = "operation"
STEP_ARM = "arm"

CONF_OPERATION = "operation"
OPERATION_DRY_RUN = "dry_run"
OPERATION_ARMED = "armed"

ARMING_CHECKS: Final = (
    "one_controller",
    "old_control_off",
    "compared",
    "controls_checked",
    "fresh_start",
    "way_back",
)
"""The checks the page of arming repeats, in the order of section 8 of the pilot guide.

``tests/ha/test_arming.py`` compares them with the markers of that list.
"""

ERROR_CONFIRM_EVERY_CHECK = "confirm_every_check"
ERROR_NO_MOVEMENT_DETECTION = "no_movement_detection"
ERROR_REPORTING_NOT_STATED = "reporting_not_stated"
ERROR_REPORTING_POLLED = "reporting_polled"
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
    -> one page per cover -> (reconfigure: dry-run or armed -> the checks)
    -> save once.
    """

    _name: str
    _group_id: str | None
    _resolved: ResolvedCovers
    _members: tuple[MemberConfig, ...]
    _last_basics: dict[str, Any] | None = None
    _member_values: dict[str, dict[str, Any]]
    _member_index: int

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
            # The pages of the settings always follow.
            last_step=False,
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

    def _pages_follow_the_features(self) -> bool:
        """Return whether pages follow the feature pages: the page of every cover does."""
        return True

    async def _async_finish(self) -> SubentryFlowResult:
        """Go on with the page of the first cover, after the feature pages."""
        if self._own_subentry_is_gone():
            return self.async_abort(reason=ABORT_SUBENTRY_REMOVED)
        stored = (
            self._get_reconfigure_subentry().data
            if self.source == SOURCE_RECONFIGURE
            else {}
        )
        self._member_values = {
            member.member_id: sound_member_values(stored, member.member_id)
            for member in self._members
        }
        self._member_index = 0
        return await self.async_step_member()

    async def async_step_member(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask what no entity can report about one cover; one page per cover.

        The position source, the tolerance, the reporting kind and time, and
        the travel times. After the last cover, a new window is saved in
        dry-run and a reconfigure goes on with "dry-run or armed".
        """
        member_id = self._members[self._member_index].member_id
        errors: dict[str, str] = {}
        if user_input is not None:
            read = member_page.read_input(user_input)
            if not read.errors:
                self._member_values[member_id] = read.own
                self._member_index += 1
                if self._member_index < len(self._members):
                    return await self.async_step_member()
                self._members = with_stated(self._members, self._member_values)
                if self.source == SOURCE_RECONFIGURE:
                    return await self.async_step_operation()
                # New windows start in dry-run (architecture document, decision 12).
                return await self._async_save(dry_run=True)
            errors = read.errors
        return self.async_show_form(
            step_id=member_page.STEP_MEMBER,
            data_schema=member_page.schema(self._member_values[member_id]),
            errors=errors,
            description_placeholders=member_page.placeholders(
                member_id, self._member_index + 1, len(self._members)
            ),
            last_step=self._member_index == len(self._members) - 1
            and self.source != SOURCE_RECONFIGURE,
        )

    def _stored_dry_run(self) -> bool:
        """Return whether the window is in dry-run now; unreadable counts as dry-run."""
        return read_window_identity(self._get_reconfigure_subentry().data).dry_run

    async def async_step_operation(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask for dry-run or armed (E11); arming needs the confirmation that follows.

        Going back to dry-run needs no confirmation. A window that is armed
        already stays armed without one, but only while arming is possible at
        all: until the runtime notices a movement by hand, "armed" leads to
        the page of the checks for every window, and that page refuses.
        """
        if self._own_subentry_is_gone():
            return self.async_abort(reason=ABORT_SUBENTRY_REMOVED)
        in_dry_run = self._stored_dry_run()
        needs_checks = in_dry_run or self._arming_refused()
        if user_input is None:
            schema = probatio.Schema(
                {
                    probatio.Required(
                        CONF_OPERATION,
                        default=OPERATION_DRY_RUN if in_dry_run else OPERATION_ARMED,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[OPERATION_DRY_RUN, OPERATION_ARMED],
                            mode=SelectSelectorMode.LIST,
                            translation_key=CONF_OPERATION,
                        )
                    )
                }
            )
            return self.async_show_form(
                step_id=STEP_OPERATION,
                data_schema=as_form_schema(schema),
                # "Armed" leads to the confirmation from dry-run, and for
                # every window while arming is refused.
                last_step=not needs_checks,
            )
        if user_input[CONF_OPERATION] == OPERATION_DRY_RUN:
            return await self._async_save(dry_run=True)
        if needs_checks:
            return await self.async_step_arm()
        return await self._async_save(dry_run=False)

    def _arming_refused(self) -> tuple[str, dict[str, str]] | None:
        """Return the error and its placeholders of a fact that refuses arming.

        No tick can outweigh these: the runtime does not notice a movement by
        hand yet, a cover of the window has no reporting kind or time stated
        on its page, or a cover is polled. A reporting time above zero is no
        refusal: it enters the deadline (ruling of the project owner,
        2026-10-01).
        """
        if not const.MOVEMENT_DETECTION_WIRED:
            return ERROR_NO_MOVEMENT_DETECTION, {}
        facts = reporting_facts(self._members)
        if facts.not_stated:
            return ERROR_REPORTING_NOT_STATED, {"covers": ", ".join(facts.not_stated)}
        if facts.polled:
            return ERROR_REPORTING_POLLED, {"covers": ", ".join(facts.polled)}
        return None

    async def async_step_arm(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Repeat the checks before arming; save only when every one is confirmed.

        A fact that refuses arming is shown when the page opens, and the page
        then saves nothing whatever is ticked.
        """
        errors: dict[str, str] = {}
        placeholders: dict[str, str] = {}
        if (refused := self._arming_refused()) is not None:
            errors["base"], placeholders = refused
        elif user_input is not None:
            if all(user_input.get(check) is True for check in ARMING_CHECKS):
                return await self._async_save(dry_run=False)
            errors["base"] = ERROR_CONFIRM_EVERY_CHECK
        schema = probatio.Schema(
            {
                probatio.Required(check, default=False): BooleanSelector()
                for check in ARMING_CHECKS
            }
        )
        return self.async_show_form(
            step_id=STEP_ARM,
            data_schema=as_form_schema(schema),
            errors=errors,
            description_placeholders=placeholders,
            last_step=True,
        )

    async def _async_save(self, *, dry_run: bool) -> SubentryFlowResult:
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
            CONF_DRY_RUN: dry_run,
        }
        if self._group_id is not None:
            data[CONF_GROUP_ID] = self._group_id
        # Only the covers that state something, and of them only what they
        # state: "members are listed only where they differ" (section 9).
        members = {
            member_id: values
            for member_id, values in self._member_values.items()
            if values
        }
        if members:
            data[CONF_MEMBERS] = members
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                title=self._name,
                data=data,
            )
        return self.async_create_entry(title=self._name, data=data)
