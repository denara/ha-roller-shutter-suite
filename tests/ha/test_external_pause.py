"""The external pause entity (E4): an entity of the user that pauses a level.

The setting ``pause_source`` of the registry of the core, with the
inheritance pattern of every optional entity. The house's own entity pauses
the house level, a group's own entity the group level, and the window level
is paused by the window's resolved entity: its own or the inherited one. An
entity that is unavailable, unknown, or neither on nor off pauses as well
(ruling 4 of block H06), and so does a faulty stored reference; protection and
the fire alarm still move the shutter. After an hour without a value a repair
issue names the level that configured the entity and the entity; it
disappears by itself with the next value.

This file is also the test that ``tests/core/fault_value_situations.py``
names for the function ``pause``, whose setting the arbiter never reads: it
shows that the cautious value of a faulty reference pauses comfort and lets
protection and fire pass.
"""

from datetime import timedelta
from typing import Any

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roller_shutter_suite.const import DOMAIN
from custom_components.roller_shutter_suite.core.model import GateKind, Layer
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from custom_components.roller_shutter_suite.core.settings import STORED_NONE
from tests.ha.controls_kit import (
    GROUP_ID,
    Alarms,
    install_alarms,
    recompute,
    setup_house,
)
from tests.ha.runtime_kit import (
    WINDOW_ID,
    advance,
    controller_of,
    monday_morning,
    settle,
)
from tests.ha.status_kit import REASON, state_of

_monday_morning = pytest.fixture(autouse=True)(monday_morning)
alarms = pytest.fixture(install_alarms)

AWAY = "input_boolean.example_away"
"""The helper a user turns on while nobody is at home."""

SOURCE = {"pause_source": AWAY}


def _reason(entry: MockConfigEntry) -> tuple[GateKind, ReasonCode, Layer | None]:
    decision = controller_of(entry, WINDOW_ID).status.decision
    assert decision is not None
    assert decision.gate is not None
    wish = decision.winning_wish
    return (
        decision.gate.kind,
        decision.gate.reason,
        None if wish is None else wish.layer,
    )


def _paused_by(hass: HomeAssistant) -> list[dict[str, Any]]:
    paused_by: list[dict[str, Any]] = state_of(hass, REASON).attributes["paused_by"]
    return paused_by


def _issues(hass: HomeAssistant) -> dict[str, ir.IssueEntry]:
    return {
        issue_id: issue
        for (domain, issue_id), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN
    }


def _on(level: str) -> dict[str, Any]:
    """Return the settings of the three levels with the entity on one of them."""
    return {level: SOURCE}


async def _set(hass: HomeAssistant, freezer: Any, state: str) -> None:
    hass.states.async_set(AWAY, state)
    await settle(hass, freezer)


@pytest.mark.parametrize(
    ("level", "causes"),
    [
        ("house", ["global", "window"]),
        ("group", ["group", "window"]),
        ("window", ["window"]),
    ],
)
async def test_an_entity_that_is_on_pauses_its_level_and_what_inherits_it(
    hass: HomeAssistant,
    freezer: Any,
    alarms: Alarms,
    level: str,
    causes: list[str],
) -> None:
    """On: paused, and the status names the level and the entity; off: it runs."""
    del alarms
    hass.states.async_set(AWAY, STATE_OFF)
    entry = await setup_house(hass, freezer, **_on(level))
    assert _reason(entry)[1] is ReasonCode.SENT

    await _set(hass, freezer, STATE_ON)
    assert _reason(entry)[1] is ReasonCode.PAUSED
    # The window inherits the entity, so it pauses the window level as well.
    assert _paused_by(hass) == [
        {"level": cause, "entity_id": AWAY, "state": "on"} for cause in causes
    ]

    await _set(hass, freezer, STATE_OFF)
    assert _reason(entry)[1] is not ReasonCode.PAUSED
    assert _paused_by(hass) == []


async def test_none_on_the_window_does_not_lift_a_pause_of_the_house(
    hass: HomeAssistant, freezer: Any, alarms: Alarms
) -> None:
    """Choosing "None" keeps the inherited entity from the window level only."""
    del alarms
    hass.states.async_set(AWAY, STATE_ON)
    entry = await setup_house(
        hass, freezer, house=SOURCE, window={"pause_source": STORED_NONE}
    )

    assert _reason(entry)[1] is ReasonCode.PAUSED
    assert _paused_by(hass) == [{"level": "global", "entity_id": AWAY, "state": "on"}]


@pytest.mark.parametrize(
    ("state", "shown"),
    [(STATE_UNAVAILABLE, "unavailable"), (STATE_UNKNOWN, "unknown"), ("home", "home")],
)
async def test_an_entity_without_a_value_pauses_and_protection_and_fire_still_pass(
    hass: HomeAssistant, freezer: Any, alarms: Alarms, state: str, shown: str
) -> None:
    """Missing data is not "no pause": comfort waits, the storm and the fire move."""
    hass.states.async_set(AWAY, state)
    entry = await setup_house(hass, freezer, window=SOURCE)

    assert _reason(entry) == (GateKind.SUPPRESS, ReasonCode.PAUSED, Layer.SCHEDULE)
    assert _paused_by(hass) == [{"level": "window", "entity_id": AWAY, "state": shown}]

    alarms.storm = True
    await recompute(hass, freezer, entry)
    assert _reason(entry)[:1] == (GateKind.SEND,)
    assert _reason(entry)[2] is Layer.PROTECTION
    alarms.fire = True
    await recompute(hass, freezer, entry)
    assert _reason(entry) == (GateKind.SEND, ReasonCode.SENT, Layer.FIRE)


async def test_an_entity_that_does_not_exist_pauses_too(
    hass: HomeAssistant, freezer: Any, alarms: Alarms
) -> None:
    """An entity that was deleted counts as unavailable."""
    del alarms
    entry = await setup_house(hass, freezer, group=SOURCE)

    assert _reason(entry)[1] is ReasonCode.PAUSED
    assert _paused_by(hass)[0] == {
        "level": "group",
        "entity_id": AWAY,
        "state": "unavailable",
    }


async def test_a_faulty_stored_reference_is_blind_and_pauses(
    hass: HomeAssistant, freezer: Any, alarms: Alarms
) -> None:
    """A group that stored no entity where one belongs: its windows are paused.

    The fault itself is reported by the repair issue of faulty settings.
    """
    del alarms
    entry = await setup_house(hass, freezer, group={"pause_source": 7})

    assert _reason(entry)[1] is ReasonCode.PAUSED
    assert {"level": "group", "entity_id": None, "state": "blind"} in _paused_by(hass)
    assert f"setting_fault_{GROUP_ID}_pause_source" in _issues(hass)


@pytest.mark.parametrize(
    ("level", "kind", "owner", "name"),
    [
        ("house", "global", None, "Roller Shutter Suite"),
        ("group", "group", GROUP_ID, "Example group"),
        ("window", "window", WINDOW_ID, "Example window"),
    ],
)
async def test_after_an_hour_without_a_value_a_repair_issue_names_level_and_entity(  # noqa: PLR0913 - the three levels
    hass: HomeAssistant,
    freezer: Any,
    *,
    alarms: Alarms,
    level: str,
    kind: str,
    owner: str | None,
    name: str,
) -> None:
    """Reported once, at the level that configured it; gone with the next value."""
    del alarms
    hass.states.async_set(AWAY, STATE_UNAVAILABLE)
    entry = await setup_house(hass, freezer, **_on(level))
    issue_id = f"pause_source_blind_{owner or entry.entry_id}"
    start = controller_of(entry, WINDOW_ID).clock.now()

    await advance(hass, freezer, start + timedelta(minutes=59))
    assert issue_id not in _issues(hass)

    await advance(hass, freezer, start + timedelta(minutes=61))
    issues = _issues(hass)
    # The window inherits the entity, but only its source reports it.
    assert [key for key in issues if key.startswith("pause_source_blind")] == [issue_id]
    issue = issues[issue_id]
    assert issue.translation_key == f"pause_source_blind_{kind}"
    assert issue.translation_placeholders == {"name": name, "entity": AWAY}
    assert issue.is_fixable is False

    await _set(hass, freezer, STATE_OFF)
    assert issue_id not in _issues(hass)
    assert _reason(entry)[1] is not ReasonCode.PAUSED


@pytest.mark.parametrize(
    ("stored", "hours"),
    [(7200, 2), (30, 1), ("not a duration", 1)],
    ids=["two hours", "out of range", "unreadable"],
)
async def test_the_time_before_the_issue_is_the_blind_time_of_the_house(
    hass: HomeAssistant,
    freezer: Any,
    alarms: Alarms,
    stored: object,
    hours: int,
) -> None:
    """One setting for every kind of source: ``source_blind_after`` of the house.

    A faulty stored value is the fault value, the default hour.
    """
    del alarms
    hass.states.async_set(AWAY, STATE_UNAVAILABLE)
    entry = await setup_house(
        hass, freezer, house={**SOURCE, "source_blind_after": stored}
    )
    issue_id = f"pause_source_blind_{entry.entry_id}"
    start = controller_of(entry, WINDOW_ID).clock.now()

    await advance(hass, freezer, start + timedelta(hours=hours, minutes=-1))
    assert issue_id not in _issues(hass)
    await advance(hass, freezer, start + timedelta(hours=hours, minutes=1))
    assert issue_id in _issues(hass)


async def test_the_clock_of_a_blind_entity_survives_a_reload(
    hass: HomeAssistant, freezer: Any, alarms: Alarms
) -> None:
    """Forty minutes, a reload, twenty-one more: the issue appears; it stays over a reload."""
    del alarms
    hass.states.async_set(AWAY, STATE_UNKNOWN)
    entry = await setup_house(hass, freezer, window=SOURCE)
    issue_id = f"pause_source_blind_{WINDOW_ID}"
    start = controller_of(entry, WINDOW_ID).clock.now()

    await advance(hass, freezer, start + timedelta(minutes=40))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await advance(hass, freezer, start + timedelta(minutes=61))
    assert issue_id in _issues(hass)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert issue_id in _issues(hass)

    # The entity is no longer used: the issue goes with the next set-up.
    subentry = entry.subentries[WINDOW_ID]
    hass.config_entries.async_update_subentry(
        entry, subentry, data={**subentry.data, "settings": {}}
    )
    await hass.async_block_till_done()
    assert issue_id not in _issues(hass)


async def test_the_diagnostics_show_the_entity_and_why_it_pauses(
    hass: HomeAssistant, freezer: Any, alarms: Alarms
) -> None:
    """Each level with its switches, its entity and what the entity does."""
    del alarms
    hass.states.async_set(AWAY, STATE_ON)
    entry = await setup_house(hass, freezer, house=SOURCE)

    report = entry.runtime_data.board.window_report(WINDOW_ID)
    house, group, window = report["levels"]
    assert house["pause_source"] == AWAY
    assert house["pause_source_pauses"] == "on"
    assert group["pause_source"] is None
    assert window["pause_source"] == AWAY
    assert report["effective"]["paused"] is True


async def test_each_entity_recomputes_the_levels_that_use_it_and_keeps_its_own_clock(
    hass: HomeAssistant, freezer: Any, alarms: Alarms
) -> None:
    """Two entities: one of the house, one of the window, each with its own issue.

    A change of the entity of the house pauses; the entity of the window
    goes from unavailable to unknown, which is still no value: its clock
    keeps running from the first moment without one.
    """
    del alarms
    party = "binary_sensor.example_party"
    hass.states.async_set(AWAY, STATE_OFF)
    hass.states.async_set(party, STATE_UNAVAILABLE)
    entry = await setup_house(
        hass, freezer, house=SOURCE, window={"pause_source": party}
    )
    start = controller_of(entry, WINDOW_ID).clock.now()
    assert _paused_by(hass) == [
        {"level": "window", "entity_id": party, "state": "unavailable"}
    ]

    await advance(hass, freezer, start + timedelta(minutes=30))
    await _set(hass, freezer, STATE_ON)
    hass.states.async_set(party, STATE_UNKNOWN)
    await settle(hass, freezer)
    assert _paused_by(hass) == [
        {"level": "global", "entity_id": AWAY, "state": "on"},
        {"level": "window", "entity_id": party, "state": "unknown"},
    ]

    await advance(hass, freezer, start + timedelta(minutes=61))
    blind = [key for key in _issues(hass) if key.startswith("pause_source_blind")]
    assert blind == [f"pause_source_blind_{WINDOW_ID}"]
