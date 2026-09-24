"""The status entities of a window: set-up, naming, states driven by decisions.

Every window of the tests is named "Example window", so its device is named
so and its entities are ``sensor.example_window_reason`` and so on. The time
is Monday 10:00 in a named zone; the daily routine has fixed times (07:00 and
20:00 on workdays).
"""

from datetime import timedelta
from typing import Any

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, EntityCategory
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from custom_components.roller_shutter_suite.const import DOMAIN
from custom_components.roller_shutter_suite.core.model import Layer
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from custom_components.roller_shutter_suite.events import history_of
from custom_components.roller_shutter_suite.record import REASON_OPTIONS
from tests.ha.helpers import set_cover
from tests.ha.runtime_kit import (
    COVER,
    FIXED_ROUTINE,
    WINDOW_ID,
    advance,
    controller_of,
    local,
    monday_morning,
    runtime_of,
    settle,
    setup_window,
    window_data,
)
from tests.ha.status_kit import (
    DRY_RUN,
    ENTITIES,
    NEXT_ACTION,
    OVERRIDE,
    REASON,
    TARGET,
    FireAlarm,
    state_of,
)

_monday_morning = pytest.fixture(autouse=True)(monday_morning)


async def test_every_window_gets_its_entities_on_its_device(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Unique IDs, entity names from translations, the device and subentry of the window."""
    entry = await setup_window(hass, freezer=freezer)
    entities = er.async_get(hass)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, WINDOW_ID), entry.entry_id
    )
    assert device is not None

    expected = {
        REASON: ("sensor", "active_reason", None),
        TARGET: ("sensor", "target_position", None),
        NEXT_ACTION: ("sensor", "next_action", None),
        OVERRIDE: ("binary_sensor", "override_active", None),
        DRY_RUN: ("binary_sensor", "dry_run", EntityCategory.DIAGNOSTIC),
    }
    for entity_id, (domain, key, category) in expected.items():
        registered = entities.async_get(entity_id)
        assert registered is not None, entity_id
        assert registered.domain == domain
        assert registered.unique_id == f"{WINDOW_ID}_{key}"
        assert registered.translation_key == key
        assert registered.has_entity_name
        assert registered.entity_category is category
        assert registered.device_id == device.id
        assert registered.config_entry_id == entry.entry_id
        assert registered.config_subentry_id == WINDOW_ID
    assert hass.states.get(REASON) is not None
    assert state_of(hass, REASON).attributes["friendly_name"] == "Example window Reason"


async def test_the_reason_sensor_is_an_enumeration_of_every_reason_code(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Its options are the codes of the core; its state is one of them."""
    await setup_window(hass, freezer=freezer)
    state = hass.states.get(REASON)
    assert state is not None

    assert state.attributes["options"] == [code.value for code in ReasonCode]
    assert list(REASON_OPTIONS) == state.attributes["options"]
    assert state.attributes["device_class"] == "enum"
    # At 10:00 the day position is wanted and the open cover is there already.
    assert state.state == ReasonCode.SCHEDULE_DAY
    assert state.attributes["gate_reason"] == ReasonCode.TARGET_REACHED
    assert state_of(hass, TARGET).state == "100"
    assert state_of(hass, OVERRIDE).state == STATE_OFF
    assert state_of(hass, DRY_RUN).state == STATE_OFF
    next_action = state_of(hass, NEXT_ACTION)
    # 20:00 in the zone of the tests is 18:00 UTC in September.
    assert next_action.state == "2026-09-21T18:00:00+00:00"
    assert next_action.attributes["target"] == 0
    assert next_action.attributes["reason"] == ReasonCode.SCHEDULE_NIGHT


async def test_the_reason_sensor_changes_when_and_only_when_the_decision_changes(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Recomputes with the same decision write nothing; a new decision writes once."""
    entry = await setup_window(hass, freezer=freezer)
    controller = controller_of(entry)
    changes: list[str] = []

    @callback
    def _changed(event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        assert new is not None
        changes.append(new.state)

    async_track_state_change_event(hass, [REASON], _changed)
    before = controller.status.recomputes
    for _ in range(3):
        controller.async_request_recompute()
        await settle(hass, freezer)
    assert controller.status.recomputes == before + 3
    assert changes == []

    await advance(hass, freezer, local(20, 0, second=1))
    assert changes
    assert changes[0] == ReasonCode.SCHEDULE_NIGHT
    state = hass.states.get(REASON)
    assert state is not None
    assert state.attributes["layer"] == "schedule"
    assert state.attributes["wish_reason"] == ReasonCode.SCHEDULE_NIGHT
    assert state.attributes["target"] == 0


def _count_writes(hass: HomeAssistant, entity_id: str) -> list[str]:
    """Return a list that gets one entry per state written for the entity."""
    writes: list[str] = []

    @callback
    def _written(event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        assert new is not None
        writes.append(new.state)

    async_track_state_change_event(hass, [entity_id], _written)
    return writes


async def test_a_deferral_without_a_known_end_writes_one_state(
    hass: HomeAssistant, freezer: Any
) -> None:
    """A foreign movement at the evening: many recomputes, one write, one decision kept.

    The core re-evaluates such a deferral no later than a few minutes after
    each recompute; that instant moves with the clock and is no attribute.
    """
    entry = await setup_window(hass, freezer=freezer)
    set_cover(hass, COVER, position=100, state="closing")
    await settle(hass, freezer)
    writes = _count_writes(hass, REASON)
    recent = history_of(hass)[WINDOW_ID].recent

    await advance(hass, freezer, local(20, 0, second=1))
    assert writes == [ReasonCode.MOVEMENT_IN_FLIGHT]
    kept = len(recent)
    for _ in range(6):
        freezer.tick(timedelta(minutes=5))
        await settle(hass, freezer)

    assert controller_of(entry).status.recomputes >= 6  # noqa: PLR2004 - six ticks
    assert writes == [ReasonCode.MOVEMENT_IN_FLIGHT]
    assert len(recent) == kept
    assert "reevaluated_no_later_than" not in state_of(hass, REASON).attributes


async def test_the_wish_stays_the_reason_while_its_command_is_under_way(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The evening closing: the reason stays "Daily routine: night" until the cover is there."""
    await setup_window(hass, freezer=freezer)
    writes = _count_writes(hass, REASON)

    await advance(hass, freezer, local(20, 0, second=1))
    # The cover starts moving: the window is looked at again, the command is
    # still under way.
    set_cover(hass, COVER, position=100, state="closing")
    await settle(hass, freezer)
    state = state_of(hass, REASON)
    assert state.attributes["gate_reason"] == ReasonCode.DUPLICATE_COMMAND
    assert state.state == ReasonCode.SCHEDULE_NIGHT
    set_cover(hass, COVER, position=0, state="closed")
    await settle(hass, freezer)

    assert set(writes) == {ReasonCode.SCHEDULE_NIGHT}


async def test_the_attributes_say_why_the_other_layers_did_not_win(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The record names every other layer with its reason, and the constraints applied."""
    entry = await setup_window(hass, freezer=freezer)
    controller = controller_of(entry)
    alarm = FireAlarm()
    alarm.install(controller)
    await advance(hass, freezer, local(20, 0, second=1))

    state = hass.states.get(REASON)
    assert state is not None
    attributes = state.attributes
    assert attributes["layer"] == "schedule"
    others = {item["layer"]: item for item in attributes["other_layers"]}
    assert set(others) == {layer.value for layer in Layer} - {"schedule"}
    assert others["fire"] == {"layer": "fire", "reason": "inactive", "function": "fire"}
    assert others["sleep"]["reason"] == ReasonCode.NOT_CONFIGURED
    assert attributes["constraints"] == []
    assert attributes["gate_outcome"] == "send"
    assert attributes["faults"] == []
    assert attributes["dry_run"] is False


async def test_a_constraint_that_leaves_no_target_is_the_reason(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The morning only raises: an open shutter stays above a lower morning position."""
    await setup_window(
        hass,
        house=FIXED_ROUTINE | {"schedule_morning_position": 50},
        freezer=freezer,
    )
    state = state_of(hass, REASON)

    assert state.state == ReasonCode.ONLY_RAISE
    assert state.attributes["wish_reason"] == ReasonCode.SCHEDULE_DAY
    assert state.attributes["constraints"] == [
        {"constraint": "direction", "reason": "only_raise", "target": None}
    ]
    assert state.attributes["gate_outcome"] is None
    assert state_of(hass, TARGET).state == "unknown"


async def test_a_window_in_dry_run_shows_the_hypothetical_outcome(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The would-be position, or the rule that would have held the wish back."""
    set_cover(hass, COVER, position=50)
    await setup_window(
        hass, window_data(dry_run=True), covers_present=False, freezer=freezer
    )
    state = hass.states.get(REASON)
    assert state is not None

    assert state.state == ReasonCode.DRY_RUN
    assert state.attributes["dry_run"] is True
    assert state.attributes["gate_rule"] == "dry_run"
    assert state.attributes["would_send"] == 100  # noqa: PLR2004 - fully open
    assert state.attributes["wish_reason"] == ReasonCode.SCHEDULE_DAY
    assert state_of(hass, DRY_RUN).state == STATE_ON


async def test_entities_become_unavailable_with_the_cover_and_recover_without_reload(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Unavailable while no cover is; back with the next recompute that sees it."""
    entry = await setup_window(hass, freezer=freezer)
    runtime = runtime_of(entry)
    controller = controller_of(entry)

    hass.states.async_set(COVER, STATE_UNAVAILABLE)
    await settle(hass, freezer)
    for entity_id in ENTITIES:
        assert state_of(hass, entity_id).state == STATE_UNAVAILABLE, entity_id

    set_cover(hass, COVER)
    await settle(hass, freezer)
    for entity_id in ENTITIES:
        assert state_of(hass, entity_id).state != STATE_UNAVAILABLE, entity_id
    # The same runtime and controller: nothing was reloaded.
    assert runtime_of(entry) is runtime
    assert controller_of(entry) is controller


async def test_entities_of_a_window_without_a_controller_are_unavailable(
    hass: HomeAssistant, freezer: Any
) -> None:
    """A window that is not controlled shows nothing it does not know."""
    entry = await setup_window(hass, freezer=freezer)

    runtime_of(entry).async_remove_window(WINDOW_ID)
    await hass.async_block_till_done()
    for entity_id in ENTITIES:
        assert state_of(hass, entity_id).state == STATE_UNAVAILABLE, entity_id


async def test_entities_before_the_first_decision_are_unavailable(
    hass: HomeAssistant, freezer: Any
) -> None:
    """A cover that has not appeared yet: the entities wait with it."""
    await setup_window(hass, covers_present=False, freezer=freezer)

    for entity_id in ENTITIES:
        assert state_of(hass, entity_id).state == STATE_UNAVAILABLE, entity_id
