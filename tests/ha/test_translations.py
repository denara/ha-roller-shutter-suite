"""Every string a user sees has a translation key, in English and in German.

The key parity of the three generated files, and that they are current, is
checked in ``tests/scripts/test_build_translations.py``, which also runs where
Home Assistant does not. Here the forms themselves are asked what they show.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from custom_components.roller_shutter_suite import windows
from custom_components.roller_shutter_suite.const import (
    ENTRY_TITLE,
    PROVISIONAL_TRAVEL_TIME,
)
from custom_components.roller_shutter_suite.core.model import (
    CapabilityProfile,
    MemberConfig,
    TriggerKind,
)
from custom_components.roller_shutter_suite.core.settings import (
    Level,
    PartialSettings,
    SettingProblem,
    schedule_trigger_keys,
)
from custom_components.roller_shutter_suite.features import CATALOG
from custom_components.roller_shutter_suite.flow import (
    group_flow,
    inheritance,
    window_flow,
)
from custom_components.roller_shutter_suite.flow.model import (
    Catalog,
    GroupParent,
    LevelContext,
)
from scripts import build_translations
from tests.ha.helpers import EXAMPLE_CATALOG, EXAMPLE_FEATURE

INTEGRATION_DIR = (
    Path(__file__).parents[2] / "custom_components" / "roller_shutter_suite"
)
FILES = [name for names in build_translations.languages().values() for name in names]
FLOWS = {
    Level.GLOBAL: ("config",),
    Level.GROUP: ("config_subentries", "group"),
    Level.WINDOW: ("config_subentries", "window"),
}
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def _load(relative_path: str) -> dict[str, Any]:
    content: dict[str, Any] = json.loads(
        (INTEGRATION_DIR / relative_path).read_text(encoding="utf-8")
    )
    return content


def _flow(strings: dict[str, Any], level: Level) -> dict[str, Any]:
    node = strings
    for key in FLOWS[level]:
        node = node[key]
    return node


def _context(level: Level) -> LevelContext:
    if level is Level.GLOBAL:
        return LevelContext(level=level, own={}, house_title=ENTRY_TITLE)
    group = (
        GroupParent("g1", "South", PartialSettings()) if level is Level.WINDOW else None
    )
    context = LevelContext(
        level=level,
        own={},
        house_title=ENTRY_TITLE,
        house=PartialSettings(),
        group=group,
    )
    if level is Level.WINDOW:
        # A cover that cannot stop, so a setting that needs "stop" shows its stand-in.
        context.members = (
            MemberConfig(
                "cover.example_roof",
                CapabilityProfile(
                    supports_open_close=True,
                    supports_set_position=True,
                    supports_stop=False,
                    reports_position=True,
                    travel_time_up=PROVISIONAL_TRAVEL_TIME,
                    travel_time_down=PROVISIONAL_TRAVEL_TIME,
                ),
            ),
        )
    return context


def _assert_step_is_translated(
    step: dict[str, Any], catalog: Catalog, fields: Any, level: Level
) -> None:
    """Every field has a label and a helper text; every placeholder is supplied."""
    context = _context(level)
    inherited = inheritance.inherited_settings(catalog, context)
    schema = inheritance.build_schema(catalog, fields, context, inherited).schema
    supplied = set(inheritance.build_placeholders(catalog, fields, context, inherited))

    shown = [step["title"], step["description"]]
    for marker, selector in schema.items():
        key = str(marker)
        if key == inheritance.SECTION_EXPERT:
            section = step["sections"][key]
            shown += [section["name"], section["description"]]
            for inner in selector.schema.schema:
                shown.append(section["data"][str(inner)])
                shown.append(section["data_description"][str(inner)])
        else:
            shown += [step["data"][key], step["data_description"][key]]
    assert all(shown)
    # Only what is shown needs its placeholders; the label of a field that a
    # stand-in replaces is not shown.
    used = set(_PLACEHOLDER.findall(" ".join(shown)))
    assert used <= supplied, f"placeholders without a value: {sorted(used - supplied)}"


@pytest.mark.parametrize("path", FILES)
@pytest.mark.parametrize("level", list(FLOWS))
def test_every_field_the_forms_show_is_translated(path: str, level: Level) -> None:
    """The shipped files cover what the flows of the three levels really show."""
    flow = _flow(_load(path), level)

    assert flow["step"]["features"]["data"]["schedule_enabled"]
    for feature in CATALOG.features:
        for page in feature.steps:
            step = flow["step"][feature.step_id(page)]
            _assert_step_is_translated(step, CATALOG, page.fields, level)


@pytest.mark.parametrize("path", FILES)
def test_brightness_threshold_names_lux(path: str) -> None:
    """The key of the setting carries no unit; the form and its texts do."""
    for level in FLOWS:
        step = _flow(_load(path), level)["step"]["feature_daily_routine_general"]
        assert "lux" in step["data"]["schedule_brightness_threshold_lux"].lower()
        assert "schedule_brightness_threshold" not in step["data"]


@pytest.mark.parametrize("path", FILES)
def test_trigger_kinds_share_one_translated_choice(path: str) -> None:
    """Every value of the enumeration of the core has a label, and "inherit" has one."""
    options = _load(path)["selector"]["schedule_trigger_kind"]["options"]

    assert set(options) == {"inherit", *(kind.value for kind in TriggerKind)}


@pytest.mark.parametrize("path", FILES)
def test_every_error_abort_and_menu_entry_is_translated(path: str) -> None:
    """Errors exist on every level, because the generated steps exist on every level."""
    strings = _load(path)
    errors = [
        value for name, value in vars(inheritance).items() if name.startswith("ERROR_")
    ]
    assert errors

    for level in FLOWS:
        flow = _flow(strings, level)
        for error in errors:
            assert flow["error"][error]
        assert flow["abort"]["reconfigure_successful"]
    window = _flow(strings, Level.WINDOW)
    assert window["error"][window_flow.ERROR_NO_COVERS]
    assert window["error"][window_flow.ERROR_COVER_IN_USE]
    assert window["error"][window_flow.ERROR_NAME_BLANK]
    assert window["error"][window_flow.ERROR_GROUP_REMOVED]
    group = _flow(strings, Level.GROUP)
    assert group["error"][group_flow.ERROR_NAME_BLANK]
    assert group["abort"][group_flow.ABORT_SUBENTRY_REMOVED]
    assert window["abort"][window_flow.ABORT_SUBENTRY_REMOVED]
    for step, options in (
        (window_flow.STEP_MEMBERS, (window_flow.STEP_MEMBERS_ACCEPT,)),
        (window_flow.STEP_DEGRADED, (window_flow.STEP_DEGRADED_ACCEPT,)),
    ):
        for option in (*options, window_flow.STEP_BASICS):
            assert window["step"][step]["menu_options"][option]
    for subentry_type in ("group", "window"):
        node = strings["config_subentries"][subentry_type]
        assert node["entry_type"]
        assert set(node["initiate_flow"]) == {"user", "reconfigure"}
    options = strings["selector"]
    assert set(options[inheritance.TRANSLATION_KEY_SWITCH]["options"]) == {
        inheritance.INHERIT_ON,
        inheritance.INHERIT_OFF,
        inheritance.ON,
        inheritance.OFF,
    }
    assert set(options[inheritance.TRANSLATION_KEY_REFERENCE]["options"]) == {
        inheritance.INHERIT_NONE,
        inheritance.INHERIT_REFERENCE,
        inheritance.NONE,
        inheritance.OWN,
    }


@pytest.mark.parametrize("path", FILES)
def test_every_repair_issue_is_translated(path: str) -> None:
    """Each problem code of the core can be explained on each level it can occur on."""
    issues = _load(path)["issues"]
    plain = [
        value
        for name, value in vars(windows).items()
        if name.startswith("ISSUE_") and value != windows.ISSUE_SETTING_FAULT
    ]

    for key in plain:
        assert issues[key]["title"]
        assert issues[key]["description"]
    # A combination and a refusal without keys have an issue of their own.
    own_issue = {SettingProblem.COMBINATION, SettingProblem.RULE_WITHOUT_KEYS}
    for level in (Level.GLOBAL, Level.GROUP, Level.WINDOW):
        for problem in set(SettingProblem) - own_issue:
            issue = issues[
                f"{windows.ISSUE_SETTING_FAULT}_{level.value}_{problem.value}"
            ]
            assert "{key}" in issue["description"] or problem is (
                SettingProblem.LEVEL_UNREADABLE
            )
            assert ("{name}" in issue["title"]) is (level is not Level.GLOBAL)


def test_settings_are_translated_by_adding_them_to_a_fragment() -> None:
    """Registry entries, form data and a fragment: the generator needs nothing else."""
    templates = json.loads(
        (build_translations.SOURCES / "base.en.json").read_text(encoding="utf-8")
    )["_templates"]
    fragment: dict[str, Any] = json.loads(
        (build_translations.SOURCES / "features" / "daily_routine.en.json").read_text(
            encoding="utf-8"
        )
    )
    fragment["fields"] |= {
        "example_hold": {"label": "Hold to move", "description": "Made up."},
        "example_window_only": {"label": "Window only", "description": "Made up."},
    }
    fragment["unavailable"] = {
        "example_hold": {
            "label": "Hold to move: not available",
            "description": "{limited_by_supports_stop} cannot be stopped.",
        }
    }
    general = EXAMPLE_FEATURE.steps[0]

    for level in FLOWS:
        step = build_translations.feature_step(
            EXAMPLE_CATALOG, general, fragment, templates, level.value
        )
        context = _context(level)
        _assert_step_is_translated(step, EXAMPLE_CATALOG, general.fields, level)
        assert ("example_hold_unavailable" in step["data"]) is (level is Level.WINDOW)
        assert ("example_window_only" in step["data"]) is (level is Level.WINDOW)
        hint = "Leave empty to inherit."
        description = step["data_description"]["schedule_summer_first_day"]
        assert (hint in description) is context.inherits
        assert ("{schedule_summer_first_day_inherited}" in description) is (
            context.inherits
        )
        if level is Level.WINDOW:
            schema = inheritance.build_schema(
                EXAMPLE_CATALOG,
                general.fields,
                context,
                inheritance.inherited_settings(EXAMPLE_CATALOG, context),
            ).schema
            assert "example_hold_unavailable" in {str(marker) for marker in schema}


def test_texts_of_generated_settings_are_generated_from_the_same_lists() -> None:
    """Day type, edge, field: one text per field of a trigger, not thirty-six."""
    for language in build_translations.languages():
        fragment = json.loads(
            (
                build_translations.SOURCES
                / "features"
                / f"daily_routine.{language}.json"
            ).read_text(encoding="utf-8")
        )
        texts = build_translations.field_texts(fragment)

        assert set(schedule_trigger_keys()) <= set(texts)
        assert not set(schedule_trigger_keys()) & set(fragment["fields"])
        for key in schedule_trigger_keys():
            assert "[" not in texts[key]["label"] + texts[key]["description"], key
