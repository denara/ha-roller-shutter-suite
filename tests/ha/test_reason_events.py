"""Reason events: what fires them, what they carry, and that they do not repeat.

The time is Monday 10:00 in a named zone; the daily routine has fixed times
(07:00 and 20:00 on workdays). The recording actuator stands in for the
covers, so an own command moves nothing and a cover stays where the test put
it.
"""

from datetime import timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.roller_shutter_suite.const import DOMAIN
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.ha.helpers import set_cover
from tests.ha.runtime_kit import (
    COVER,
    WINDOW_ID,
    advance,
    commands_sent,
    controller_of,
    local,
    monday_morning,
    settle,
    setup_window,
    window_data,
)
from tests.ha.status_kit import FireAlarm, collect_reason_events, controls

_monday_morning = pytest.fixture(autouse=True)(monday_morning)


async def _tick(hass: HomeAssistant, freezer: Any, times: int, minutes: int) -> None:
    """Let time pass in steps; every step recomputes at least once."""
    for _ in range(times):
        freezer.tick(timedelta(minutes=minutes))
        await settle(hass, freezer)


async def test_a_sent_command_fires_one_event_with_the_window_and_the_reason(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Payload: subentry ID, device ID, name, reason, layer, target, gate outcome."""
    fired = collect_reason_events(hass)
    entry = await setup_window(hass, freezer=freezer)
    assert fired == []  # the day position is reached: nothing wanted

    await advance(hass, freezer, local(20, 0, second=1))
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, WINDOW_ID), entry.entry_id
    )
    assert device is not None
    assert [c.target.value for c in commands_sent(entry)] == [0]
    assert fired == [
        {
            "subentry_id": WINDOW_ID,
            "device_id": device.id,
            "name": "Example window",
            "reason": ReasonCode.SENT,
            "layer": "schedule",
            "wish_class": "comfort",
            "wish_reason": ReasonCode.SCHEDULE_NIGHT,
            "target": 0,
            "gate": "send",
            "gate_rule": None,
            "dry_run": False,
            "until": None,
        }
    ]

    # While the command is under way the outcome is the same; then the cover
    # reports the target. Nothing more is fired, however often it is recomputed.
    await _tick(hass, freezer, times=1, minutes=0)
    set_cover(hass, COVER, position=0, state="closed")
    await _tick(hass, freezer, times=6, minutes=5)
    assert len(fired) == 1


async def test_a_held_back_movement_fires_once_per_change_of_outcome(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Paused: one event, however often the window is recomputed; resumed: one more."""
    fired = collect_reason_events(hass)
    entry = await setup_window(hass, freezer=freezer)
    controller = controller_of(entry)
    controller.controls = lambda: controls(paused=True)

    await advance(hass, freezer, local(20, 0, second=1))
    await _tick(hass, freezer, times=6, minutes=5)
    assert [(e["reason"], e["gate"], e["target"]) for e in fired] == [
        (ReasonCode.PAUSED, "suppress", 0)
    ]
    assert fired[0]["gate_rule"] == "pause"
    assert commands_sent(entry) == []

    controller.controls = controls
    controller.async_request_recompute()
    await settle(hass, freezer)
    assert [e["reason"] for e in fired] == [ReasonCode.PAUSED, ReasonCode.SENT]


async def test_a_would_be_command_in_dry_run_fires_once(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The simulated command runs out and is simulated again: still one event."""
    fired = collect_reason_events(hass)
    set_cover(hass, COVER, position=50)
    entry = await setup_window(
        hass, window_data(dry_run=True), covers_present=False, freezer=freezer
    )

    await _tick(hass, freezer, times=12, minutes=5)
    assert [(e["reason"], e["target"], e["dry_run"]) for e in fired] == [
        (ReasonCode.DRY_RUN, 100, True)
    ]
    assert fired[0]["gate_rule"] == "dry_run"
    assert commands_sent(entry) == []


async def test_reaching_the_target_ends_the_outcome(
    hass: HomeAssistant, freezer: Any
) -> None:
    """After the target is reached, the same wish later is a new movement and fires."""
    fired = collect_reason_events(hass)
    set_cover(hass, COVER, position=50)
    entry = await setup_window(hass, covers_present=False, freezer=freezer)
    assert [e["reason"] for e in fired] == [ReasonCode.SENT]
    set_cover(hass, COVER, position=100)
    await settle(hass, freezer)

    # Lowered again: the day position is wanted again, first after the
    # minimum time between two movements.
    set_cover(hass, COVER, position=50)
    for _ in range(20):
        await _tick(hass, freezer, times=1, minutes=1)
        if [e["reason"] for e in fired].count(ReasonCode.SENT) == 2:  # noqa: PLR2004
            set_cover(hass, COVER, position=100)
            break
    await _tick(hass, freezer, times=4, minutes=5)
    assert [e["reason"] for e in fired] == [
        ReasonCode.SENT,
        ReasonCode.MIN_INTERVAL,
        ReasonCode.SENT,
    ]
    assert fired[1]["gate"] == "defer"
    assert fired[1]["until"] is not None
    assert len(commands_sent(entry)) == 2  # noqa: PLR2004 - two movements


async def test_the_fire_event_fires_at_once_in_dry_run_and_sends_nothing(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Fire in dry-run: the event says what would have been sent; nothing moves."""
    fired = collect_reason_events(hass)
    set_cover(hass, COVER, position=0, state="closed")
    entry = await setup_window(
        hass, window_data(dry_run=True), covers_present=False, freezer=freezer
    )
    controller = controller_of(entry)
    alarm = FireAlarm()
    alarm.install(controller)
    # In the evening the closed shutter is where the routine wants it.
    await advance(hass, freezer, local(20, 0, second=1))
    fired.clear()

    alarm.active = True
    controller.async_request_recompute()
    await settle(hass, freezer)
    assert [(e["layer"], e["reason"], e["target"]) for e in fired] == [
        ("fire", ReasonCode.DRY_RUN, 100)
    ]
    assert fired[0]["wish_reason"] == ReasonCode.FIRE_ALARM
    assert fired[0]["wish_class"] == "fire"
    assert commands_sent(entry) == []


async def test_the_fire_event_fires_at_once_under_maintenance_lock_and_sends_nothing(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Fire under maintenance lock: the event names the lock; nothing moves."""
    fired = collect_reason_events(hass)
    set_cover(hass, COVER, position=0)
    entry = await setup_window(hass, covers_present=False, freezer=freezer)
    controller = controller_of(entry)
    controller.controls = lambda: controls(maintenance_lock=True)
    alarm = FireAlarm()
    alarm.install(controller)
    controller.async_request_recompute()
    await settle(hass, freezer)
    before = len(commands_sent(entry))
    fired.clear()

    alarm.active = True
    controller.async_request_recompute()
    await settle(hass, freezer)
    assert [(e["layer"], e["reason"], e["gate"]) for e in fired] == [
        ("fire", ReasonCode.MAINTENANCE_LOCK, "suppress")
    ]
    assert fired[0]["target"] == 100  # noqa: PLR2004 - fully open
    assert len(commands_sent(entry)) == before

    await _tick(hass, freezer, times=3, minutes=5)
    assert len(fired) == 1


async def test_the_memory_of_the_last_outcome_survives_a_reload(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Every change of the configuration reloads the entry; the outcome is not fired again."""
    fired = collect_reason_events(hass)
    set_cover(hass, COVER, position=50)
    entry = await setup_window(
        hass, window_data(dry_run=True), covers_present=False, freezer=freezer
    )
    assert len(fired) == 1

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await settle(hass, freezer)
    assert len(fired) == 1
