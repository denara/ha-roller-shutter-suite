"""SPIKE S2, questions 1 and 7: what a subentry flow can do.

Several steps, a collapsed section, selectors, a menu, branching on feature
switches, steps contributed by feature modules, and the life cycle of a
subentry: create, reconfigure, remove.
"""

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, section
from homeassistant.helpers.selector import NumberSelector, SelectSelector

from custom_components.roller_shutter_suite.config_flow import (
    RollerShutterSuiteConfigFlow,
)
from custom_components.roller_shutter_suite.const import (
    CONF_SETTINGS,
    SUBENTRY_GROUP,
    SUBENTRY_WINDOW,
)
from custom_components.roller_shutter_suite.features import FEATURES
from custom_components.roller_shutter_suite.flow.group_flow import GroupSubentryFlow
from custom_components.roller_shutter_suite.flow.window_flow import WindowSubentryFlow
from tests.ha.s2_helpers import (
    INHERIT_ALL_SWITCHES,
    add_group,
    marker_of,
    run_subentry_flow,
    schema_keys,
    set_cover,
    setup_entry,
)


async def test_subentry_flow_has_several_steps_selectors_and_a_section(
    hass: HomeAssistant,
) -> None:
    """A group flow walks basics -> features -> feature step with a section."""
    entry = await setup_entry(hass)

    result = await run_subentry_flow(hass, entry, SUBENTRY_GROUP, [])
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "basics"

    result = await run_subentry_flow(hass, entry, SUBENTRY_GROUP, [{"name": "South"}])
    assert result["step_id"] == "features"
    assert schema_keys(result) == [
        "enable_daily_routine",
        "enable_shading",
        "enable_buttons",
    ]
    assert isinstance(
        result["data_schema"].schema[marker_of(result, "enable_shading")],
        SelectSelector,
    )

    result = await run_subentry_flow(
        hass, entry, SUBENTRY_GROUP, [{"name": "South"}, INHERIT_ALL_SWITCHES]
    )
    assert result["step_id"] == "feature_daily_routine"
    assert schema_keys(result) == [
        "open_in_morning",
        "morning_position",
        "evening_position",
        "expert",
    ]
    expert = result["data_schema"].schema[marker_of(result, "expert")]
    assert isinstance(expert, section)
    assert expert.options == {"collapsed": True}
    assert [str(m) for m in expert.schema.schema] == ["random_offset"]
    assert isinstance(
        result["data_schema"].schema[marker_of(result, "morning_position")],
        NumberSelector,
    )


async def test_section_input_arrives_nested_and_is_stored_flat(
    hass: HomeAssistant,
) -> None:
    """The input of a section arrives under the section's key."""
    entry = await setup_entry(hass)

    group = await add_group(
        hass, entry, "South", {"morning_position": 80, "expert": {"random_offset": 5}}
    )

    assert group.data[CONF_SETTINGS] == {"morning_position": 80, "random_offset": 5}


async def test_only_enabled_features_get_a_step(hass: HomeAssistant) -> None:
    """Progressive configuration: the flow branches on the feature switches."""
    entry = await setup_entry(hass)

    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_GROUP,
        [
            {"name": "South"},
            {
                "enable_daily_routine": "off",
                "enable_shading": "on",
                "enable_buttons": "inherit_off",
            },
        ],
    )

    # Daily routine is skipped, shading follows, buttons never appear.
    assert result["step_id"] == "feature_shading"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"shading_position": 0, "use_forecast": "inherit_off"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SETTINGS] == {
        "enable_daily_routine": False,
        "enable_shading": True,
        "shading_position": 0,
    }


async def test_a_feature_validates_its_own_step(hass: HomeAssistant) -> None:
    """The validation hook of a feature module produces a field error."""
    entry = await setup_entry(hass)

    result = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_GROUP,
        [
            {"name": "South"},
            INHERIT_ALL_SWITCHES,
            {
                "open_in_morning": "inherit_on",
                "morning_position": 20,
                "evening_position": 50,
                "expert": {},
            },
        ],
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "feature_daily_routine"
    assert result["errors"] == {"evening_position": "evening_above_morning"}


def test_every_feature_contributes_its_step_to_every_flow() -> None:
    """Modular layout: no flow class names a feature; the registry does."""
    for flow_class in (
        RollerShutterSuiteConfigFlow,
        GroupSubentryFlow,
        WindowSubentryFlow,
    ):
        for feature in FEATURES:
            assert callable(getattr(flow_class, f"async_step_{feature.step_id}"))


async def test_subentry_is_created_reconfigured_and_removed(
    hass: HomeAssistant,
) -> None:
    """The whole life cycle of a window subentry through the public API."""
    entry = await setup_entry(hass)
    set_cover(hass, "cover.example_window")

    created = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [
            {"name": "Example window", "covers": ["cover.example_window"]},
            INHERIT_ALL_SWITCHES,
            {"open_in_morning": "inherit_on", "expert": {}},
        ],
    )
    assert created["type"] is FlowResultType.CREATE_ENTRY
    (window,) = entry.subentries.values()
    assert window.subentry_type == SUBENTRY_WINDOW
    assert window.title == "Example window"
    assert window.data["covers"] == ["cover.example_window"]
    assert window.data["dry_run"] is True
    assert window.data[CONF_SETTINGS] == {}

    # Reconfigure: the form is pre-filled, the flow ends with an abort.
    form = await run_subentry_flow(
        hass, entry, SUBENTRY_WINDOW, [], reconfigure=window.subentry_id
    )
    assert form["step_id"] == "basics"
    assert marker_of(form, "name").description == {"suggested_value": "Example window"}
    changed = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [
            {"name": "Renamed window", "covers": ["cover.example_window"]},
            INHERIT_ALL_SWITCHES,
            {"open_in_morning": "off", "morning_position": 0, "expert": {}},
        ],
        reconfigure=window.subentry_id,
    )
    assert changed["type"] is FlowResultType.ABORT
    assert changed["reason"] == "reconfigure_successful"
    window = entry.subentries[window.subentry_id]
    assert window.title == "Renamed window"
    assert window.data[CONF_SETTINGS] == {
        "open_in_morning": False,
        "morning_position": 0,
    }

    # Remove: the same call the frontend's delete command makes.
    assert hass.config_entries.async_remove_subentry(entry, window.subentry_id)
    await hass.async_block_till_done()
    assert entry.subentries == {}
