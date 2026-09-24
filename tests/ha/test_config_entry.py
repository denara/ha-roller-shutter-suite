"""The config entry of the house: creating, changing, unloading, removing."""

from typing import Any

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.selector import BooleanSelector

from custom_components.roller_shutter_suite.const import (
    CONF_SETTINGS,
    DOMAIN,
    ENTRY_TITLE,
    SUBENTRY_WINDOW,
)
from custom_components.roller_shutter_suite.core.settings import STORED_NONE
from custom_components.roller_shutter_suite.features import CATALOG
from custom_components.roller_shutter_suite.stored import level_settings
from tests.ha.helpers import (
    DAY_HOUSE,
    GENERAL_HOUSE,
    MOVEMENT_HOUSE,
    ROUTINE_HOUSE,
    SWITCHES_HOUSE,
    marker_of,
    new_entry,
    schema_keys,
    schema_of,
    setup_entry,
    subentry_data,
)

BRIGHTNESS_DELAY_SECONDS = 600


async def _submit(
    hass: HomeAssistant, result: Any, inputs: list[dict[str, Any]]
) -> Any:
    for user_input in inputs:
        assert result["type"] is FlowResultType.FORM, result
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input
        )
    await hass.async_block_till_done()
    return result


async def test_user_flow_creates_entry_that_sets_up(hass: HomeAssistant) -> None:
    """The user flow asks for the values of the house and creates the entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    # Feature switches first; on the house a switch is a plain toggle.
    assert result["step_id"] == "features"
    assert isinstance(schema_of(result)["schedule_enabled"], BooleanSelector)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], SWITCHES_HOUSE
    )
    assert result["step_id"] == "feature_daily_routine_general"
    # The house inherits from nothing: "none" or an own selection, no "inherit".
    choice = schema_of(result)["schedule_workday_source_choice"]
    assert choice.config["options"] == ["none", "own"]
    # The conditional morning opening is not built, so no form offers its source.
    assert "morning_condition_source_choice" not in schema_keys(result)

    steps = []
    for user_input in ROUTINE_HOUSE[1:]:
        steps.append(result["step_id"])
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input
        )
    await hass.async_block_till_done()

    assert steps == [
        "feature_daily_routine_general",
        "feature_daily_routine_workday",
        "feature_daily_routine_weekend",
        "feature_daily_routine_holiday",
        "feature_movement_general",
    ]
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == ENTRY_TITLE
    # Every field of the house has a value, stored in the form the core reads.
    settings = result["data"][CONF_SETTINGS]
    assert set(settings) == CATALOG.form_keys
    assert settings["schedule_enabled"] is True
    assert settings["schedule_workday_source"] == STORED_NONE
    assert settings["schedule_workday_morning_time"] == "07:00:00"
    assert settings["schedule_summer_first_day"] == "05-01"
    assert settings["schedule_brightness_delay"] == BRIGHTNESS_DELAY_SECONDS
    assert settings["schedule_workday_evening_kind"] == "sun_event"
    assert None not in settings.values()
    assert not level_settings(result["data"], CATALOG.registry).faults
    assert result["result"].state is ConfigEntryState.LOADED
    assert not ir.async_get(hass).issues


async def test_house_is_changed_through_reconfigure(hass: HomeAssistant) -> None:
    """There is no options flow; reconfigure changes the values of the house."""
    entry = await setup_entry(hass)

    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "features"

    general = GENERAL_HOUSE | {
        "schedule_workday_source_choice": "own",
        "schedule_workday_source": "binary_sensor.example_workday",
        "schedule_evening_position": 0.0,
    }
    result = await _submit(
        hass,
        result,
        [SWITCHES_HOUSE, general, DAY_HOUSE, DAY_HOUSE, DAY_HOUSE, MOVEMENT_HOUSE],
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    settings = entry.data[CONF_SETTINGS]
    assert settings["schedule_workday_source"] == "binary_sensor.example_workday"
    assert settings["schedule_evening_position"] == 0
    assert entry.state is ConfigEntryState.LOADED

    # The form shows the own values again.
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], SWITCHES_HOUSE
    )
    assert marker_of(result, "schedule_workday_source_choice").default() == "own"
    assert marker_of(result, "schedule_evening_position").default() == 0


async def test_daily_routine_switched_off_for_the_house_has_no_pages(
    hass: HomeAssistant,
) -> None:
    """Only the features that are switched on get their pages; movement has no switch."""
    entry = await setup_entry(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await _submit(hass, result, [{"schedule_enabled": False}])
    assert result["step_id"] == "feature_movement_general"
    result = await _submit(hass, result, [MOVEMENT_HOUSE])

    assert result["reason"] == "reconfigure_successful"
    settings = entry.data[CONF_SETTINGS]
    assert settings == {
        "schedule_enabled": False,
        "motor_min_change": 5,
        "motor_min_interval": 600,
        "stagger_gap": 2,
        "reevaluate_after": 300,
    }


async def test_integration_has_no_options_flow(hass: HomeAssistant) -> None:
    """The entry offers reconfigure and no options flow."""
    entry = await setup_entry(hass)

    assert not entry.supports_options
    assert entry.supports_reconfigure


async def test_entry_sets_up(hass: HomeAssistant) -> None:
    """An existing entry is set up and carries its runtime data."""
    entry = await setup_entry(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.windows == {}
    assert entry.runtime_data.not_set_up == ()


async def test_second_entry_is_refused(hass: HomeAssistant) -> None:
    """Home Assistant refuses a second entry: the manifest allows only one."""
    new_entry().add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_entry_unloads(hass: HomeAssistant) -> None:
    """A loaded entry unloads cleanly."""
    entry = await setup_entry(hass)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_removing_the_entry_removes_its_repair_issues(
    hass: HomeAssistant,
) -> None:
    """No repair issue outlives the entry it is about."""
    entry = await setup_entry(
        hass,
        subentries=[
            subentry_data(SUBENTRY_WINDOW, "Example window", {}, "window_unreadable")
        ],
    )
    issues = ir.async_get(hass)
    assert [issue for domain, issue in issues.issues if domain == DOMAIN]

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert not [issue for domain, issue in issues.issues if domain == DOMAIN]
