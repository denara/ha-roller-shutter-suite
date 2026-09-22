"""Decision 15: faulty stored data never brings the config entry down.

A function that protects or restricts movement falls back to the next level; a
function that creates comfort wishes pauses for the windows concerned; unknown
keys are reported and harmless; everything is reported with level, key and
reason. A window is not set up only if its covers cannot be read.
"""

from enum import StrEnum
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.roller_shutter_suite import features
from custom_components.roller_shutter_suite.const import (
    CONF_COVERS,
    CONF_DRY_RUN,
    CONF_GROUP_ID,
    CONF_SETTINGS,
    DOMAIN,
    SUBENTRY_GROUP,
    SUBENTRY_WINDOW,
)
from custom_components.roller_shutter_suite.core.model import (
    FunctionId,
    MemberConfig,
    WindowConfig,
)
from custom_components.roller_shutter_suite.core.settings import (
    STORED_NONE,
    WINDOW_SETTINGS,
    FaultAction,
    GroupLevel,
    Level,
    PartialSettings,
    ReportedFault,
    ResolvedSettings,
    SettingRules,
    WindowResolution,
    resolve_settings,
    resolve_window,
)
from custom_components.roller_shutter_suite.flow.model import Catalog
from tests.ha.helpers import (
    NO_STOP,
    routine_inherit,
    run_subentry_flow,
    set_cover,
    setup_entry,
    subentry_data,
)

FROST_DEFAULT = 90
HOUSE_POSITION = 80
GROUP_POSITION = 60
PAUSED_BY_AN_UNREADABLE_LEVEL = {FunctionId.SCHEDULE, FunctionId.SHADING}


def _window(
    subentry_id: str,
    cover: str,
    settings: Any,
    **identity: Any,
) -> dict[str, Any]:
    return subentry_data(
        SUBENTRY_WINDOW,
        f"Window {subentry_id}",
        {CONF_COVERS: [cover], CONF_DRY_RUN: True, CONF_SETTINGS: settings} | identity,
        subentry_id,
    )


def _issues(hass: HomeAssistant) -> dict[str, ir.IssueEntry]:
    return {
        issue_id: issue
        for (domain, issue_id), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN
    }


async def test_entry_loads_and_only_the_window_without_readable_covers_is_not_set_up(
    hass: HomeAssistant,
) -> None:
    """Five faults in one entry: it loads, and each issue names level, key and reason."""
    for name in ("comfort", "protection", "unknown", "grouped"):
        set_cover(hass, f"cover.example_{name}")
    entry = await setup_entry(
        hass,
        subentries=[
            subentry_data(SUBENTRY_GROUP, "Unreadable group", {CONF_SETTINGS: 7}, "g1"),
            _window(
                "comfort", "cover.example_comfort", {"schedule_morning_position": "up"}
            ),
            _window("protection", "cover.example_protection", {"frost_position": None}),
            _window("unknown", "cover.example_unknown", {"example_from_the_future": 1}),
            _window("grouped", "cover.example_grouped", {}, **{CONF_GROUP_ID: "g1"}),
            subentry_data(
                SUBENTRY_WINDOW,
                "Window without covers",
                {CONF_COVERS: "cover.example_text", CONF_SETTINGS: {}},
                "broken",
            ),
        ],
    )

    assert entry.state is ConfigEntryState.LOADED
    windows = entry.runtime_data.windows
    assert set(windows) == {"comfort", "protection", "unknown", "grouped"}
    assert entry.runtime_data.not_set_up == ("broken",)

    # A faulty setting of a function that creates comfort wishes pauses that
    # function, for this window only.
    comfort = windows["comfort"].resolution
    assert comfort.settings.disabled_functions == {FunctionId.SCHEDULE}
    assert comfort.config is not None
    assert comfort.config.disabled_functions == {FunctionId.SCHEDULE}
    # A faulty setting of a function that protects falls back and never fails.
    # No other level supplies a valid value, so its cautious fault value
    # applies, which for the frost position is the default, stated on purpose.
    protection = windows["protection"].resolution.settings
    assert protection.disabled_functions == frozenset()
    assert protection.values["frost_position"].value.value == FROST_DEFAULT
    assert protection.values["frost_position"].cautious
    own_faults = [fault for fault in protection.faults if fault.level is Level.WINDOW]
    assert [fault.action for fault in own_faults] == [
        FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE
    ]
    # An unknown key is reported and harmless.
    assert windows["unknown"].resolution.settings.disabled_functions == frozenset()
    # A group that is unreadable as a whole counts as not present: comfort pauses.
    assert (
        windows["grouped"].resolution.settings.disabled_functions
        == PAUSED_BY_AN_UNREADABLE_LEVEL
    )
    # Nobody can see what the group had set, so what protects runs on its
    # cautious values. The core names the group once more for each of them;
    # the one issue of the group stands for all (checked below).
    hidden = [
        fault
        for fault in windows["grouped"].resolution.settings.faults
        if fault.action is FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE
    ]
    assert "frost_source" in {fault.key for fault in hidden}
    assert {fault.level for fault in hidden} == {Level.GROUP}

    issues = _issues(hass)
    expected = {
        "setting_fault_comfort_schedule_morning_position": (
            "setting_fault_window_unreadable",
            {"name": "Window comfort", "key": "schedule_morning_position"},
        ),
        "setting_fault_protection_frost_position": (
            "setting_fault_window_unreadable",
            {"name": "Window protection", "key": "frost_position"},
        ),
        "setting_fault_unknown_example_from_the_future": (
            "setting_fault_window_unknown_setting",
            {"name": "Window unknown", "key": "example_from_the_future"},
        ),
        "setting_fault_g1_settings": (
            "setting_fault_group_level_unreadable",
            {"name": "Unreadable group", "key": "settings"},
        ),
        "window_covers_unreadable_broken": (
            "window_covers_unreadable",
            {"window": "Window without covers"},
        ),
    }
    assert set(issues) == set(expected)
    for issue_id, (translation_key, placeholders) in expected.items():
        assert issues[issue_id].translation_key == translation_key
        assert issues[issue_id].translation_placeholders == placeholders
        assert issues[issue_id].is_fixable is False


@pytest.mark.parametrize(
    "covers",
    [None, [], "cover.example_text", ["cover.example_a", "cover.example_a"], [7]],
    ids=["null", "empty", "text", "twice", "number"],
)
async def test_covers_that_cannot_be_read(hass: HomeAssistant, covers: Any) -> None:
    """Whatever is wrong with the covers, only this window stays away."""
    set_cover(hass, "cover.example_sound")
    entry = await setup_entry(
        hass,
        subentries=[
            subentry_data(SUBENTRY_WINDOW, "Broken", {CONF_COVERS: covers}, "broken"),
            _window("sound", "cover.example_sound", {}),
        ],
    )

    assert entry.state is ConfigEntryState.LOADED
    assert set(entry.runtime_data.windows) == {"sound"}
    assert "window_covers_unreadable_broken" in _issues(hass)


async def test_fault_of_the_house_and_of_a_group_is_reported_without_any_window(
    hass: HomeAssistant,
) -> None:
    """The levels are judged also while no window inherits from them."""
    await setup_entry(
        hass,
        {
            CONF_SETTINGS: {
                "schedule_morning_position": STORED_NONE,
                "covering_type": "roller_shutter",
            }
        },
        subentries=[
            subentry_data(
                SUBENTRY_GROUP,
                "South",
                # The reader accepts an hour; the window configuration allows
                # a random offset of at most 30 minutes.
                {CONF_SETTINGS: {"schedule_random_offset": 3600}},
                "g1",
            )
        ],
    )

    issues = _issues(hass)
    assert {issue_id: issue.translation_key for issue_id, issue in issues.items()} == {
        "setting_fault_global_schedule_morning_position": (
            "setting_fault_global_none_not_allowed"
        ),
        "setting_fault_global_covering_type": "setting_fault_global_not_inheritable",
        "setting_fault_g1_schedule_random_offset": "setting_fault_group_invalid",
    }
    assert issues[
        "setting_fault_g1_schedule_random_offset"
    ].translation_placeholders == {"name": "South", "key": "schedule_random_offset"}


async def test_house_without_the_settings_mapping_is_unreadable_as_a_whole(
    hass: HomeAssistant,
) -> None:
    """The flows and the migration always write the mapping, so its absence is a fault."""
    set_cover(hass, "cover.example_window")
    entry = await setup_entry(
        hass, {}, subentries=[_window("w1", "cover.example_window", {})]
    )

    assert entry.state is ConfigEntryState.LOADED
    settings = entry.runtime_data.windows["w1"].resolution.settings
    assert settings.disabled_functions == PAUSED_BY_AN_UNREADABLE_LEVEL
    issue = _issues(hass)["setting_fault_global_settings"]
    assert issue.translation_key == "setting_fault_global_level_unreadable"


async def test_combination_issue_names_both_levels_and_keys(
    hass: HomeAssistant,
) -> None:
    """Each value alone is fine; the issue says which values of which levels clash."""
    set_cover(hass, "cover.example_window")
    entry = await setup_entry(
        hass,
        {CONF_SETTINGS: {"schedule_workday_evening_not_before": "17:00:00"}},
        subentries=[
            subentry_data(
                SUBENTRY_GROUP,
                "South",
                {CONF_SETTINGS: {"schedule_workday_morning_time": "21:00:00"}},
                "g1",
            ),
            _window("w1", "cover.example_window", {}, **{CONF_GROUP_ID: "g1"}),
        ],
    )

    issues = _issues(hass)
    assert set(issues) == {
        "setting_combination_g1.schedule_workday_morning_time"
        "_global.schedule_workday_evening_not_before"
    }
    issue = next(iter(issues.values()))
    assert issue.translation_key == "setting_combination"
    assert issue.translation_placeholders == {
        "settings": (
            'schedule_workday_morning_time ("South"), '
            'schedule_workday_evening_not_before ("Roller Shutter Suite")'
        )
    }
    # The schedule pauses for the window the combination reaches; nothing else does.
    settings = entry.runtime_data.windows["w1"].resolution.settings
    assert settings.disabled_functions == {FunctionId.SCHEDULE}


async def test_group_that_is_gone_falls_back_to_the_house_and_saving_repairs_it(
    hass: HomeAssistant,
) -> None:
    """Removing a group cannot be prevented; the window inherits from the house."""
    set_cover(hass, "cover.example_window")
    entry = await setup_entry(
        hass,
        {CONF_SETTINGS: {"schedule_morning_position": HOUSE_POSITION}},
        subentries=[
            subentry_data(
                SUBENTRY_GROUP,
                "South",
                {CONF_SETTINGS: {"schedule_morning_position": GROUP_POSITION}},
                "g1",
            ),
            _window("w1", "cover.example_window", {}, **{CONF_GROUP_ID: "g1"}),
        ],
    )
    settings = entry.runtime_data.windows["w1"].resolution.settings
    assert settings.values["schedule_morning_position"].value.value == GROUP_POSITION
    assert not _issues(hass)

    assert hass.config_entries.async_remove_subentry(entry, "g1")
    await hass.async_block_till_done()

    settings = entry.runtime_data.windows["w1"].resolution.settings
    assert settings.values["schedule_morning_position"].value.value == HOUSE_POSITION
    assert settings.disabled_functions == frozenset()
    issues = _issues(hass)
    assert set(issues) == {"group_missing_w1"}
    assert issues["group_missing_w1"].translation_placeholders == {
        "window": "Window w1"
    }

    # The form does not suggest the group that is gone; saving stores "no group".
    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [
            {"name": "Window w1", "covers": ["cover.example_window"]},
            *routine_inherit(),
        ],
        reconfigure="w1",
    )

    assert result["reason"] == "reconfigure_successful"
    assert CONF_GROUP_ID not in entry.subentries["w1"].data
    assert not _issues(hass)


@pytest.mark.parametrize("reference", [None, 7, ""], ids=["null", "number", "empty"])
async def test_group_reference_that_cannot_be_read_pauses_comfort(
    hass: HomeAssistant, reference: Any
) -> None:
    """``null`` is no second spelling of "no group": it is a fault, and comfort pauses."""
    set_cover(hass, "cover.example_window")
    entry = await setup_entry(
        hass,
        subentries=[
            _window("w1", "cover.example_window", {}, **{CONF_GROUP_ID: reference})
        ],
    )

    window = entry.runtime_data.windows["w1"]
    assert window.resolution.settings.disabled_functions == (
        PAUSED_BY_AN_UNREADABLE_LEVEL
    )
    assert window.resolution.config is not None
    assert set(_issues(hass)) == {"group_reference_unreadable_w1"}


async def test_dry_run_that_cannot_be_read_counts_as_dry_run(
    hass: HomeAssistant,
) -> None:
    """A window whose dry-run state is unknown must not move."""
    set_cover(hass, "cover.example_window")
    entry = await setup_entry(
        hass,
        subentries=[
            subentry_data(
                SUBENTRY_WINDOW,
                "Kitchen",
                {
                    CONF_COVERS: ["cover.example_window"],
                    CONF_DRY_RUN: "no",
                    CONF_SETTINGS: {},
                },
                "w1",
            )
        ],
    )

    assert entry.runtime_data.windows["w1"].dry_run is True
    assert set(_issues(hass)) == {"dry_run_unreadable_w1"}


async def test_saving_the_form_repairs_a_faulty_setting(hass: HomeAssistant) -> None:
    """The form starts from the sound values, so saving writes no faulty one back."""
    set_cover(hass, "cover.example_window")
    entry = await setup_entry(
        hass,
        subentries=[
            _window(
                "w1",
                "cover.example_window",
                {
                    "schedule_morning_position": "up",
                    "example_from_the_future": 1,
                    "schedule_evening_position": 20,
                    # No form shows these two; they stay as they are.
                    "frost_position": 80,
                    "morning_condition_source": "binary_sensor.example_awake",
                },
            )
        ],
    )
    assert len(_issues(hass)) == 2  # noqa: PLR2004 - the two faulty keys

    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [
            {"name": "Kitchen", "covers": ["cover.example_window"]},
            *routine_inherit({"schedule_evening_position": 20}),
        ],
        reconfigure="w1",
    )

    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries["w1"].data[CONF_SETTINGS] == {
        "schedule_evening_position": 20,
        "frost_position": 80,
        "morning_condition_source": "binary_sensor.example_awake",
    }
    assert not _issues(hass)


async def test_removing_the_faulty_window_removes_its_issue(
    hass: HomeAssistant,
) -> None:
    """An issue disappears when its subentry is removed."""
    entry = await setup_entry(
        hass, subentries=[subentry_data(SUBENTRY_WINDOW, "Broken", {}, "broken")]
    )
    assert set(_issues(hass)) == {"window_covers_unreadable_broken"}

    assert hass.config_entries.async_remove_subentry(entry, "broken")
    await hass.async_block_till_done()

    assert not _issues(hass)


@pytest.mark.usefixtures("example_catalog")
async def test_own_value_the_covers_cannot_use_is_reported(hass: HomeAssistant) -> None:
    """A masked own value is no fault; the issue names window, setting and covers."""
    set_cover(hass, "cover.example_roof", NO_STOP)
    await setup_entry(
        hass, subentries=[_window("w1", "cover.example_roof", {"example_hold": True})]
    )

    issues = _issues(hass)
    assert set(issues) == {"option_unavailable_w1_example_hold"}
    assert issues["option_unavailable_w1_example_hold"].translation_placeholders == {
        "window": "Window w1",
        "key": "example_hold",
        "covers": "cover.example_roof",
    }


def _use_resolver(monkeypatch: pytest.MonkeyPatch, resolve: Any) -> None:
    monkeypatch.setattr(
        features,
        "CATALOG",
        Catalog(
            registry=features.CATALOG.registry,
            features=features.CATALOG.features,
            resolve=resolve,
        ),
    )


async def test_rule_without_keys_is_reported_once(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refusal that names no keys is an error of the integration and says so."""

    def resolve(
        *,
        window_id: str,
        members: tuple[MemberConfig, ...],
        global_settings: PartialSettings,
        window_settings: PartialSettings,
        group: GroupLevel | None = None,
    ) -> WindowResolution:
        identity = WindowConfig(window_id=window_id, members=members)

        def build(effective: Any, disabled: frozenset[FunctionId]) -> object:
            if disabled:
                return identity
            raise ValueError("refused without keys")

        settings = resolve_settings(
            WINDOW_SETTINGS,
            capabilities=identity.capability_states,
            members=members,
            global_settings=global_settings,
            window_settings=window_settings,
            group=group,
            rules=SettingRules(lambda key, value: None, build),
        )
        return WindowResolution(identity, settings)

    _use_resolver(monkeypatch, resolve)
    set_cover(hass, "cover.example_window")
    entry = await setup_entry(
        hass, subentries=[_window("w1", "cover.example_window", {})]
    )

    assert entry.state is ConfigEntryState.LOADED
    assert set(_issues(hass)) == {"rule_without_keys"}


async def test_problem_code_of_a_later_core_gets_a_general_text(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A problem or an action this layer does not know yet is explained, never raised."""

    class LaterProblem(StrEnum):
        BRAND_NEW = "brand_new"

    class LaterAction(StrEnum):
        CAUTIOUS_VALUE = "cautious_value"

    later: Any = LaterProblem.BRAND_NEW
    action: Any = LaterAction.CAUTIOUS_VALUE

    def resolve(**levels: Any) -> WindowResolution:
        resolution = resolve_window(**levels)
        if levels["window_id"] != "w1":
            return resolution
        extra = (
            ReportedFault("frost_position", Level.WINDOW, later, "new", action),
            ReportedFault("settings", Level.BUILT_IN, later, "new", action),
        )
        settings = ResolvedSettings(
            resolution.settings.values, (*resolution.settings.faults, *extra)
        )
        return WindowResolution(resolution.config, settings)

    _use_resolver(monkeypatch, resolve)
    set_cover(hass, "cover.example_window")
    entry = await setup_entry(
        hass, subentries=[_window("w1", "cover.example_window", {})]
    )

    assert entry.state is ConfigEntryState.LOADED
    issues = _issues(hass)
    assert {issue_id: issue.translation_key for issue_id, issue in issues.items()} == {
        "setting_fault_w1_frost_position": "setting_fault_window_other",
        # A fault that names no stored level is explained as one of the house.
        "setting_fault_built_in_settings": "setting_fault_global_other",
    }
