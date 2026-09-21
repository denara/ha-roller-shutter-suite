"""The set-up with the registry of the core as it is: faults are reported, the entry loads."""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.roller_shutter_suite.const import (
    CONF_COVERS,
    CONF_DRY_RUN,
    CONF_SETTINGS,
    DOMAIN,
    SUBENTRY_WINDOW,
)
from custom_components.roller_shutter_suite.core.model import FunctionId, WindowConfig
from tests.ha.helpers import set_cover, setup_entry, subentry_data


async def test_window_is_resolved_with_the_resolver_of_the_core(
    hass: HomeAssistant,
) -> None:
    """A sound window gets its complete configuration, with its covers as members."""
    set_cover(hass, "cover.example_left")
    set_cover(hass, "cover.example_right")
    entry = await setup_entry(
        hass,
        {CONF_SETTINGS: {"morning_condition_source": "binary_sensor.example_awake"}},
        subentries=[
            subentry_data(
                SUBENTRY_WINDOW,
                "Bay",
                {
                    CONF_COVERS: ["cover.example_left", "cover.example_right"],
                    CONF_DRY_RUN: True,
                    CONF_SETTINGS: {},
                },
                "w1",
            )
        ],
    )

    config = entry.runtime_data.windows["w1"].resolution.config
    assert isinstance(config, WindowConfig)
    assert config.window_id == "w1"
    assert [member.member_id for member in config.members] == [
        "cover.example_left",
        "cover.example_right",
    ]
    assert config.morning_condition_source == "binary_sensor.example_awake"
    assert config.disabled_functions == frozenset()


async def test_faulty_comfort_setting_pauses_the_schedule_and_is_reported(
    hass: HomeAssistant,
) -> None:
    """A number where a source belongs: the schedule pauses, everything else runs."""
    set_cover(hass, "cover.example_window")
    entry = await setup_entry(
        hass,
        subentries=[
            subentry_data(
                SUBENTRY_WINDOW,
                "Kitchen",
                {
                    CONF_COVERS: ["cover.example_window"],
                    CONF_DRY_RUN: True,
                    CONF_SETTINGS: {"morning_condition_source": 7},
                },
                "w1",
            )
        ],
    )

    assert entry.state is ConfigEntryState.LOADED
    config = entry.runtime_data.windows["w1"].resolution.config
    assert config is not None
    assert config.disabled_functions == {FunctionId.SCHEDULE}
    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, "setting_fault_w1_morning_condition_source"
    )
    assert issue is not None
    assert issue.translation_key == "setting_fault_window_unreadable"
    assert issue.translation_placeholders == {
        "name": "Kitchen",
        "key": "morning_condition_source",
    }
