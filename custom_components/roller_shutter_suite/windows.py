"""From the stored config entry to the resolved windows and what has to be reported.

Reading is isolated per subentry: a faulty group or window never brings the
config entry down (decision 15 of ``docs/architecture.md``). What a fault in
stored settings costs is decided by the resolver of the core: a function that
protects or restricts movement falls back to the next level, a function that
creates comfort wishes pauses for the windows concerned. This module only
hands the levels in and turns the result into repair issues.

**A window is not set up only if its covers cannot be read.** A group that is
gone counts as not present: the window inherits from the house and an issue
names it. A reference to a group that cannot be read (``null``, for example)
is a data fault: the group level counts as unreadable as a whole, so the
comfort functions of that window pause until the window has been saved again.
"""

from dataclasses import dataclass, field
from typing import Final, cast

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant

from . import const
from .capabilities import member_configs, reporting_facts, with_stated
from .const import SUBENTRY_GROUP, SUBENTRY_WINDOW
from .core.model import MemberConfig
from .core.settings import (
    FaultAction,
    GroupLevel,
    Level,
    MissingCapability,
    PartialSettings,
    ReportedFault,
    ResolvedSettings,
    SettingProblem,
    WindowResolution,
)
from .flow.model import PROBE_MEMBER, PROBE_WINDOW_ID, Catalog
from .issues import Issue
from .stored import (
    level_settings,
    member_capability_settings,
    read_window_identity,
)

_UNREADABLE_REFERENCE: Final = "unreadable_reference"

ISSUE_COVERS_UNREADABLE: Final = "window_covers_unreadable"
ISSUE_GROUP_MISSING: Final = "group_missing"
ISSUE_GROUP_REFERENCE_UNREADABLE: Final = "group_reference_unreadable"
ISSUE_DRY_RUN_UNREADABLE: Final = "dry_run_unreadable"
ISSUE_ARMED_WITHOUT_DETECTION: Final = "armed_without_movement_detection"
ISSUE_ARMED_WITHOUT_REPORTING: Final = "armed_without_reporting"
ISSUE_OPTION_UNAVAILABLE: Final = "option_unavailable"
ISSUE_SETTING_FAULT: Final = "setting_fault"
ISSUE_COMBINATION: Final = "setting_combination"
ISSUE_RULE_WITHOUT_KEYS: Final = "rule_without_keys"

EXPLAINED_PROBLEMS: Final = frozenset(
    {
        SettingProblem.UNREADABLE,
        SettingProblem.NONE_NOT_ALLOWED,
        SettingProblem.INVALID,
        SettingProblem.NOT_INHERITABLE,
        SettingProblem.UNKNOWN_SETTING,
        SettingProblem.LEVEL_UNREADABLE,
    }
)
"""The problem codes that have a translated explanation of their own."""

PROBLEM_OTHER: Final = "other"
"""The explanation for a problem code that a later version of the core adds."""


@dataclass(frozen=True, slots=True)
class WindowRuntime:
    """A window that is set up: its subentry, its members and its resolved settings."""

    subentry_id: str
    title: str
    dry_run: bool
    resolution: WindowResolution


@dataclass(slots=True)
class EntryResolution:
    """Everything the set-up of the config entry learned from the stored data."""

    windows: dict[str, WindowRuntime] = field(default_factory=dict)
    not_set_up: list[str] = field(default_factory=list)
    issues: dict[str, Issue] = field(default_factory=dict)

    def report(self, issue: Issue) -> None:
        """Keep an issue; the same fault seen through several windows counts once."""
        self.issues[issue.issue_id] = issue


@dataclass(frozen=True, slots=True)
class _Levels:
    """The levels of the entry as the resolver takes them, with their names."""

    entry: ConfigEntry
    house: PartialSettings
    groups: dict[str, PartialSettings]

    def name(self, fault: ReportedFault, window: ConfigSubentry | None) -> str:
        """Return the name the user gave to the level a fault lies on."""
        if fault.level is Level.GROUP and fault.group_id is not None:
            return self.entry.subentries[fault.group_id].title
        if fault.level is Level.WINDOW and window is not None:
            return window.title
        return self.entry.title

    @staticmethod
    def kind(fault: ReportedFault) -> str:
        """Return the level an issue speaks of: the house, a group or a window.

        A fault that names no stored level is explained as one of the house,
        which is where its name and its repair point to.
        """
        if fault.level in (Level.GROUP, Level.WINDOW):
            return fault.level.value
        return Level.GLOBAL.value

    def owner(self, fault: ReportedFault, window: ConfigSubentry | None) -> str:
        """Return an identifier of the level a fault lies on, for the issue ID."""
        if fault.level is Level.GROUP and fault.group_id is not None:
            return fault.group_id
        if fault.level is Level.WINDOW and window is not None:
            return window.subentry_id
        return fault.level.value


def _report_faults(
    result: EntryResolution,
    levels: _Levels,
    settings: ResolvedSettings,
    window: ConfigSubentry | None,
) -> None:
    """Turn the faults of one resolution into issues that name level, key and reason."""
    combination: list[ReportedFault] = []
    for fault in settings.faults:
        if fault.group_id == _UNREADABLE_REFERENCE:
            continue
        if (
            fault.problem is SettingProblem.LEVEL_UNREADABLE
            and fault.action is FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE
        ):
            # The core names an unreadable level once as a whole and once more
            # for every setting that runs on its cautious value because of it.
            # The repair is the same for all of them, saving the level again,
            # so the one issue of the level stands for them.
            continue
        if fault.problem is SettingProblem.COMBINATION:
            combination.append(fault)
        elif fault.problem is SettingProblem.RULE_WITHOUT_KEYS:
            result.report(Issue(ISSUE_RULE_WITHOUT_KEYS, ISSUE_RULE_WITHOUT_KEYS))
        else:
            owner = levels.owner(fault, window)
            # A problem code that a later version of the core adds gets a
            # general text instead of a missing translation. What a fault
            # costs (its action) is never part of an issue, so an action that
            # is added later needs nothing here.
            problem = (
                fault.problem.value
                if fault.problem in EXPLAINED_PROBLEMS
                else PROBLEM_OTHER
            )
            result.report(
                Issue(
                    f"{ISSUE_SETTING_FAULT}_{owner}_{fault.key}",
                    f"{ISSUE_SETTING_FAULT}_{levels.kind(fault)}_{problem}",
                    {"name": levels.name(fault, window), "key": fault.key},
                )
            )
    if combination:
        # Each value alone is fine, the combination is not: one issue names
        # every level and key that is reported.
        places = sorted(
            (levels.owner(fault, window), fault.key, levels.name(fault, window))
            for fault in combination
        )
        result.report(
            Issue(
                f"{ISSUE_COMBINATION}_"
                + "_".join(f"{owner}.{key}" for owner, key, _ in places),
                ISSUE_COMBINATION,
                {"settings": ", ".join(f'{key} ("{name}")' for _, key, name in places)},
            )
        )


def _runs_in_dry_run(
    stored_dry_run: bool,
    members: tuple[MemberConfig, ...],
    result: EntryResolution,
    subentry: ConfigSubentry,
) -> bool:
    """Return whether a window runs in dry-run, and report why a stored arming is held.

    The facts that refuse arming on the page of the checks hold in operation
    alike (fail closed). While the runtime does not notice a movement by hand
    (``const.MOVEMENT_DETECTION_WIRED``), every window runs in dry-run. A
    window whose covers are not all event-driven with a known reporting time
    runs in dry-run too, with an issue that names the covers (rulings of the
    project owner, 2026-09-29 and 2026-10-01). The stored value is not
    rewritten. Loading never writes, which would reload the entry once more,
    and a window armed on purpose is armed again once its covers allow it.
    """
    if stored_dry_run:
        return True
    window_id = subentry.subentry_id
    placeholders = {"window": subentry.title}
    if not const.MOVEMENT_DETECTION_WIRED:
        result.report(
            Issue(
                f"{ISSUE_ARMED_WITHOUT_DETECTION}_{window_id}",
                ISSUE_ARMED_WITHOUT_DETECTION,
                placeholders,
            )
        )
        return True
    facts = reporting_facts(members)
    if facts.armable:
        return False
    result.report(
        Issue(
            f"{ISSUE_ARMED_WITHOUT_REPORTING}_{window_id}",
            ISSUE_ARMED_WITHOUT_REPORTING,
            # A polled cover without a time is both; it is named once.
            placeholders
            | {"covers": ", ".join(dict.fromkeys((*facts.not_stated, *facts.polled)))},
        )
    )
    return True


def _resolve_window(
    hass: HomeAssistant,
    catalog: Catalog,
    levels: _Levels,
    subentry: ConfigSubentry,
    result: EntryResolution,
) -> None:
    """Resolve one window; report what is wrong with it; never raise for stored data."""
    window_id = subentry.subentry_id
    placeholders = {"window": subentry.title}
    identity = read_window_identity(subentry.data)
    if identity.covers is None:
        result.not_set_up.append(window_id)
        result.report(
            Issue(
                f"{ISSUE_COVERS_UNREADABLE}_{window_id}",
                ISSUE_COVERS_UNREADABLE,
                placeholders,
            )
        )
        return
    if not identity.dry_run_readable:
        result.report(
            Issue(
                f"{ISSUE_DRY_RUN_UNREADABLE}_{window_id}",
                ISSUE_DRY_RUN_UNREADABLE,
                placeholders,
            )
        )
    group: GroupLevel | None = None
    if not identity.group_readable:
        group = GroupLevel(_UNREADABLE_REFERENCE, PartialSettings(unreadable=True))
        result.report(
            Issue(
                f"{ISSUE_GROUP_REFERENCE_UNREADABLE}_{window_id}",
                ISSUE_GROUP_REFERENCE_UNREADABLE,
                placeholders,
            )
        )
    elif identity.group_id is not None:
        group = GroupLevel(identity.group_id, levels.groups.get(identity.group_id))

    members: tuple[MemberConfig, ...] = with_stated(
        member_configs(hass, identity.covers),
        member_capability_settings(subentry.data),
    )
    # A window stored as armed runs in dry-run while it cannot be armed: the
    # stored data is left as it is; see ``_runs_in_dry_run``.
    dry_run = _runs_in_dry_run(identity.dry_run, members, result, subentry)
    resolution = catalog.resolve(
        window_id=window_id,
        members=members,
        global_settings=levels.house,
        window_settings=level_settings(subentry.data, catalog.registry),
        group=group,
    )
    if resolution.settings.group_missing is not None:
        result.report(
            Issue(
                f"{ISSUE_GROUP_MISSING}_{window_id}", ISSUE_GROUP_MISSING, placeholders
            )
        )
    for masked in resolution.settings.masked_own_values:
        # An own value is masked only by a capability that is missing.
        covers = cast("MissingCapability", masked.unavailable).limiting_members
        result.report(
            Issue(
                f"{ISSUE_OPTION_UNAVAILABLE}_{window_id}_{masked.key}",
                ISSUE_OPTION_UNAVAILABLE,
                placeholders | {"key": masked.key, "covers": ", ".join(covers)},
            )
        )
    _report_faults(result, levels, resolution.settings, subentry)
    result.windows[window_id] = WindowRuntime(
        subentry_id=window_id,
        title=subentry.title,
        dry_run=dry_run,
        resolution=resolution,
    )


def resolve_entry(
    hass: HomeAssistant, entry: ConfigEntry, catalog: Catalog
) -> EntryResolution:
    """Read the house, the groups and the windows of the entry and resolve every window."""
    subentries = list(entry.subentries.values())
    levels = _Levels(
        entry=entry,
        house=level_settings(entry.data, catalog.registry),
        groups={
            subentry.subentry_id: level_settings(subentry.data, catalog.registry)
            for subentry in subentries
            if subentry.subentry_type == SUBENTRY_GROUP
        },
    )
    result = EntryResolution()

    # The house and a group may have no window yet, and their faults are
    # reported all the same: an imaginary window that sets nothing shows them.
    probes: list[GroupLevel | None] = [None]
    probes.extend(
        GroupLevel(group_id, item) for group_id, item in levels.groups.items()
    )
    for group in probes:
        probe = catalog.resolve(
            window_id=PROBE_WINDOW_ID,
            members=(PROBE_MEMBER,),
            global_settings=levels.house,
            window_settings=PartialSettings(),
            group=group,
        )
        _report_faults(result, levels, probe.settings, None)

    for subentry in subentries:
        if subentry.subentry_type == SUBENTRY_WINDOW:
            _resolve_window(hass, catalog, levels, subentry, result)
    return result
