"""The logbook describes the reason events in the language of the installation."""

from collections.abc import Callable
from typing import Any

import pytest
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.integration_platform import (
    async_process_integration_platforms,
)
from homeassistant.helpers.translation import async_get_translations

from custom_components.roller_shutter_suite import logbook
from custom_components.roller_shutter_suite.const import DOMAIN, EVENT_REASON
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.ha.helpers import set_cover
from tests.ha.runtime_kit import (
    COVER,
    WINDOW_ID,
    advance,
    local,
    monday_morning,
    setup_window,
    window_data,
)
from tests.ha.status_kit import REASON, collect_reason_events, controls

_monday_morning = pytest.fixture(autouse=True)(monday_morning)

type Describe = Callable[[logbook.LogbookEvent], dict[str, Any]]


def _describer(hass: HomeAssistant) -> Describe:
    """Return the function the platform registers for the reason event."""
    registered: dict[str, tuple[str, Describe]] = {}

    def _register(domain: str, event_type: str, describe: Describe) -> None:
        registered[event_type] = (domain, describe)

    logbook.async_describe_events(hass, _register)
    domain, describe = registered[EVENT_REASON]
    assert domain == DOMAIN
    return describe


async def test_home_assistant_finds_the_logbook_platform(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The logbook looks for a platform named ``logbook``, as it does for every integration."""
    await setup_window(hass, freezer=freezer)
    found: dict[str, Any] = {}

    @callback
    def _process(hass: HomeAssistant, domain: str, platform: Any) -> None:
        del hass
        found[domain] = platform

    await async_process_integration_platforms(hass, "logbook", _process)
    await hass.async_block_till_done()
    assert found[DOMAIN] is logbook


async def test_a_sent_command_is_described_with_its_target_and_its_reason(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Name of the window, a readable message, and the reason sensor as the entity."""
    fired = collect_reason_events(hass)
    await setup_window(hass, freezer=freezer)
    await advance(hass, freezer, local(20, 0, second=1))
    describe = _describer(hass)

    described = describe(Event(EVENT_REASON, fired[0]))
    assert described == {
        "name": "Example window",
        "message": "command sent to move to 0 %. Reason: Daily routine: night.",
        "entity_id": REASON,
    }


async def test_dry_run_and_held_back_movements_are_described(
    hass: HomeAssistant, freezer: Any
) -> None:
    """What would have been sent, and what held the wish back."""
    fired = collect_reason_events(hass)
    set_cover(hass, COVER, position=50)
    entry = await setup_window(
        hass, window_data(dry_run=True), covers_present=False, freezer=freezer
    )
    describe = _describer(hass)
    assert describe(Event(EVENT_REASON, fired[0]))["message"] == (
        "dry-run, nothing moved: it would have moved to 100 %. "
        "Reason: Daily routine: day."
    )

    entry.runtime_data.runtime.windows[WINDOW_ID].controls = lambda: controls(
        paused=True
    )
    await advance(hass, freezer, local(20, 0, second=1))
    assert describe(Event(EVENT_REASON, fired[-1]))["message"] == (
        "movement to 0 % held back: Paused. Reason for the movement: Daily routine: night."
    )


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (ReasonCode.SENT, "command sent. Reason: Fire alarm."),
        (
            ReasonCode.DRY_RUN,
            "dry-run, nothing moved: it would have moved. Reason: Fire alarm.",
        ),
        (
            ReasonCode.MAINTENANCE_LOCK,
            "movement held back: Maintenance lock. Reason for the movement: Fire alarm.",
        ),
    ],
)
async def test_a_movement_without_one_common_target_is_described_without_it(
    hass: HomeAssistant, freezer: Any, reason: ReasonCode, expected: str
) -> None:
    """Members with different targets: the message names no position."""
    await setup_window(hass, freezer=freezer)
    describe = _describer(hass)
    data = {
        "subentry_id": "no_such_window",
        "name": "Example window",
        "reason": reason.value,
        "wish_reason": ReasonCode.FIRE_ALARM.value,
        "target": None,
    }

    described = describe(Event(EVENT_REASON, data))
    assert described["message"] == expected
    assert "entity_id" not in described


async def test_the_messages_follow_the_language_of_the_installation(
    hass: HomeAssistant, freezer: Any
) -> None:
    """German installation, German logbook; a language without texts names the codes."""
    fired = collect_reason_events(hass)
    await setup_window(hass, freezer=freezer)
    await advance(hass, freezer, local(20, 0, second=1))
    hass.config.language = "de"
    for category in ("entity", "common"):
        await async_get_translations(hass, "de", category, {DOMAIN})
    describe = _describer(hass)
    assert describe(Event(EVENT_REASON, fired[0]))["message"] == (
        "Befehl gesendet, auf 0 % zu fahren. Grund: Tagesablauf: Nacht."
    )

    hass.config.language = "xx"
    assert describe(Event(EVENT_REASON, fired[0]))["message"] == (
        "sent (schedule_night)"
    )


TRACKER_LINES = [
    ({"reason": "manual_detected"}, "Moved by hand.", "Von Hand bewegt."),
    (
        {"reason": "manual_detected", "position": 40},
        "Moved by hand, at 40 %.",
        "Von Hand bewegt, bei 40 %.",
    ),
    (
        {"reason": "manual_detected_member", "member_id": COVER},
        f"One cover of the window was moved by hand: {COVER}.",
        f"Ein Rollladen des Fensters wurde von Hand bewegt: {COVER}.",
    ),
    (
        {"reason": "manual_detected_member", "member_id": COVER, "position": 40},
        f"One cover of the window was moved by hand: {COVER}, at 40 %.",
        f"Ein Rollladen des Fensters wurde von Hand bewegt: {COVER}, bei 40 %.",
    ),
    (
        {"reason": "comfort_movements_threshold", "count": 41, "threshold": 40},
        "More comfort movements today than the threshold: 41 today, threshold 40.",
        "Heute mehr Komfortfahrten als der Schwellwert: heute 41, Schwellwert 40.",
    ),
]


@pytest.mark.parametrize(("data", "english", "german"), TRACKER_LINES)
async def test_an_event_of_the_tracker_is_one_line_in_both_languages(
    hass: HomeAssistant,
    freezer: Any,
    data: dict[str, Any],
    english: str,
    german: str,
) -> None:
    """The words of the reason sensor, with the cover, the position or the count."""
    await setup_window(hass, freezer=freezer)
    event = {"subentry_id": WINDOW_ID, "name": "Example window", "layer": None} | data
    describe = _describer(hass)
    described = describe(Event(EVENT_REASON, event))
    assert described["message"] == english
    assert described["entity_id"] == REASON

    hass.config.language = "de"
    for category in ("entity", "common"):
        await async_get_translations(hass, "de", category, {DOMAIN})
    assert describe(Event(EVENT_REASON, event))["message"] == german


def test_an_event_of_the_tracker_without_a_text_is_named_by_its_code() -> None:
    """A missing sentence never fails the logbook; the code stands in."""
    message = logbook.describe({"reason": "override_ended"}, {}, {})
    assert message == "override_ended"


def test_a_reason_without_a_text_is_named_by_its_code() -> None:
    """A missing word never fails the logbook; the code stands in."""
    common = {
        f"component.{DOMAIN}.common.logbook_held_back": "held: {held} / {cause} / {target}"
    }
    message = logbook.describe(
        {"reason": "paused", "wish_reason": "schedule_day", "target": 40}, {}, common
    )
    assert message == "held: paused / schedule_day / 40"
