"""The controls: pause, maintenance lock and operating mode on three levels.

Every test toggles the entity of a control through its action, as a user
does, and observes the next decision of the window. None of them reloads the
entry: the fixture ``setups`` counts the set-ups of the entry, and every test
ends with the one of its start. The installation is the one of
``controls_kit``: the house, the group "Example group" and the armed window
"Example window" in it, whose cover stands at 50 % while the daily routine
wants 100 %; the stub storm closes, the stub fire alarm opens.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, EntityCategory
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache_with_extra_data,
)

import custom_components.roller_shutter_suite as integration
from custom_components.roller_shutter_suite.const import (
    CONF_GROUP_ID,
    CONF_SETTINGS,
    DOMAIN,
    SUBENTRY_GROUP,
)
from custom_components.roller_shutter_suite.core.model import GateKind, Layer
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.ha.controls_kit import (
    GROUP,
    GROUP_ID,
    HALF_OPEN,
    HOUSE,
    LEVELS,
    WINDOW,
    Alarms,
    install_alarms,
    lock_of,
    mode_of,
    pause_of,
    recompute,
    select_mode,
    setup_house,
    turn,
)
from tests.ha.helpers import set_cover, setup_entry, subentry_data
from tests.ha.runtime_kit import (
    COVER,
    FIXED_ROUTINE,
    WINDOW_ID,
    controller_of,
    cover_calls,
    monday_morning,
    register_cover_services,
    runtime_of,
    settle,
    window_data,
    window_subentry,
)
from tests.ha.status_kit import REASON, collect_reason_events, state_of

_monday_morning = pytest.fixture(autouse=True)(monday_morning)
alarms = pytest.fixture(install_alarms)


class SetupCounter:
    """Count how often Home Assistant sets the entry up."""

    count = 0


@pytest.fixture
def setups() -> Iterator[SetupCounter]:
    """Wrap the set-up of the integration with a counter."""
    counter = SetupCounter()
    original = integration.async_setup_entry

    async def counting(
        hass: HomeAssistant, entry: integration.RollerShutterSuiteConfigEntry
    ) -> bool:
        counter.count += 1
        return await original(hass, entry)

    with patch.object(integration, "async_setup_entry", counting):
        yield counter


def _gate(entry: MockConfigEntry) -> tuple[GateKind, ReasonCode, Layer | None]:
    """Return what the last decision of the window did, why, and whose wish won."""
    decision = controller_of(entry, WINDOW_ID).status.decision
    assert decision is not None
    assert decision.gate is not None
    wish = decision.winning_wish
    return (
        decision.gate.kind,
        decision.gate.reason,
        None if wish is None else wish.layer,
    )


def _targets(hass: HomeAssistant) -> list[int]:
    return [call.target.value for call in cover_calls(hass) if call.member_id == COVER]


# ---------------------------------------------------------------------------
# The entities
# ---------------------------------------------------------------------------


async def test_every_level_has_its_controls_on_its_own_device(
    hass: HomeAssistant, freezer: Any, alarms: Alarms
) -> None:
    """Unique IDs, translated names, configuration entities, device and subentry."""
    del alarms
    entry = await setup_house(hass, freezer)
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    owners = {HOUSE: entry.entry_id, GROUP: GROUP_ID, WINDOW: WINDOW_ID}
    subentries = {HOUSE: None, GROUP: GROUP_ID, WINDOW: WINDOW_ID}
    names = {
        HOUSE: "Roller Shutter Suite",
        GROUP: "Example group",
        WINDOW: "Example window",
    }

    for level in LEVELS:
        device = devices.async_get_device_by_identifier(
            (DOMAIN, owners[level]), entry.entry_id
        )
        assert device is not None
        for entity_id, key, domain in (
            (pause_of(level), "pause", "switch"),
            (lock_of(level), "maintenance_lock", "switch"),
            (mode_of(level), "operating_mode", "select"),
        ):
            registered = entities.async_get(entity_id)
            assert registered is not None, entity_id
            assert registered.domain == domain
            assert registered.unique_id == f"{owners[level]}_{key}"
            assert registered.translation_key == key
            assert registered.has_entity_name
            assert registered.entity_category is EntityCategory.CONFIG
            assert registered.device_id == device.id
            assert registered.config_subentry_id == subentries[level]
    assert state_of(hass, pause_of(WINDOW)).attributes["friendly_name"] == (
        f"{names[WINDOW]} Pause"
    )
    assert state_of(hass, lock_of(GROUP)).attributes["friendly_name"] == (
        f"{names[GROUP]} Maintenance lock"
    )
    mode = state_of(hass, mode_of(HOUSE))
    assert mode.attributes["friendly_name"] == f"{names[HOUSE]} Operating mode"
    assert mode.attributes["options"] == ["automatic", "protection_only", "off"]
    # Without a stored state: off, off and automatic.
    for level in LEVELS:
        assert state_of(hass, pause_of(level)).state == STATE_OFF
        assert state_of(hass, lock_of(level)).state == STATE_OFF
        assert state_of(hass, mode_of(level)).state == "automatic"


async def test_controls_of_a_window_without_a_controller_are_unavailable(
    hass: HomeAssistant, freezer: Any, alarms: Alarms
) -> None:
    """The window's controls follow its controller; house and group stay available."""
    del alarms
    entry = await setup_house(hass, freezer)

    runtime_of(entry).async_remove_window(WINDOW_ID)
    await hass.async_block_till_done()

    for entity_id in (pause_of(WINDOW), lock_of(WINDOW), mode_of(WINDOW)):
        assert state_of(hass, entity_id).state == STATE_UNAVAILABLE, entity_id
    for level in (HOUSE, GROUP):
        assert state_of(hass, pause_of(level)).state == STATE_OFF
        assert state_of(hass, mode_of(level)).state == "automatic"
    # The house can still be paused; the window without a controller is skipped.
    await turn(hass, pause_of(HOUSE), on=True)
    await settle(hass, freezer)
    assert state_of(hass, pause_of(HOUSE)).state == STATE_ON


# ---------------------------------------------------------------------------
# What each control holds back, on each level, without a reload
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("level", LEVELS)
async def test_pause_holds_back_comfort_and_lets_protection_and_fire_pass(
    hass: HomeAssistant,
    freezer: Any,
    alarms: Alarms,
    setups: SetupCounter,
    level: str,
) -> None:
    """Paused on any level: comfort reads "paused"; the storm and the fire move."""
    entry = await setup_house(hass, freezer)
    assert _targets(hass) == [100]  # the comfort wish, before the pause

    await turn(hass, pause_of(level), on=True)
    await settle(hass, freezer)
    assert _gate(entry) == (GateKind.SUPPRESS, ReasonCode.PAUSED, Layer.SCHEDULE)
    assert state_of(hass, REASON).state == ReasonCode.PAUSED
    assert state_of(hass, pause_of(level)).state == STATE_ON

    alarms.storm = True
    await recompute(hass, freezer, entry)
    assert _gate(entry)[0] is GateKind.SEND
    assert _gate(entry)[2] is Layer.PROTECTION
    alarms.fire = True
    await recompute(hass, freezer, entry)
    assert _gate(entry)[2] is Layer.FIRE
    assert _targets(hass) == [100, 0, 100]

    # When the pause ends, the window is recomputed; nothing is replayed.
    alarms.storm = alarms.fire = False
    await turn(hass, pause_of(level), on=False)
    await settle(hass, freezer)
    assert _gate(entry)[2] is Layer.SCHEDULE
    assert _gate(entry)[1] is not ReasonCode.PAUSED
    assert setups.count == 1


@pytest.mark.parametrize("level", LEVELS)
async def test_maintenance_lock_holds_back_everything_and_fire_fires_its_event(
    hass: HomeAssistant,
    freezer: Any,
    alarms: Alarms,
    setups: SetupCounter,
    level: str,
) -> None:
    """Locked on any level: comfort, the storm and the fire move nothing."""
    fired = collect_reason_events(hass)
    entry = await setup_house(hass, freezer)
    before = _targets(hass)

    await turn(hass, lock_of(level), on=True)
    await settle(hass, freezer)
    assert _gate(entry)[:2] == (GateKind.SUPPRESS, ReasonCode.MAINTENANCE_LOCK)
    alarms.storm = True
    await recompute(hass, freezer, entry)
    assert _gate(entry) == (
        GateKind.SUPPRESS,
        ReasonCode.MAINTENANCE_LOCK,
        Layer.PROTECTION,
    )
    alarms.fire = True
    await recompute(hass, freezer, entry)
    assert _gate(entry) == (GateKind.SUPPRESS, ReasonCode.MAINTENANCE_LOCK, Layer.FIRE)

    assert _targets(hass) == before
    fire_events = [event for event in fired if event["layer"] == "fire"]
    assert [event["reason"] for event in fire_events] == ["maintenance_lock"]
    assert setups.count == 1


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize(
    ("mode", "comfort", "protection"),
    [
        ("protection_only", ReasonCode.MODE_PROTECTION_ONLY, None),
        ("off", ReasonCode.MODE_OFF, ReasonCode.MODE_OFF),
    ],
)
async def test_operating_mode_follows_the_table(  # noqa: PLR0913 - the table
    hass: HomeAssistant,
    freezer: Any,
    *,
    alarms: Alarms,
    setups: SetupCounter,
    level: str,
    mode: str,
    comfort: ReasonCode,
    protection: ReasonCode | None,
) -> None:
    """Protection only: comfort waits. Off: comfort and protection wait. Fire opens."""
    entry = await setup_house(hass, freezer)
    before = _targets(hass)

    await select_mode(hass, mode_of(level), mode)
    await settle(hass, freezer)
    assert state_of(hass, mode_of(level)).state == mode
    assert _gate(entry) == (GateKind.SUPPRESS, comfort, Layer.SCHEDULE)

    alarms.storm = True
    await recompute(hass, freezer, entry)
    if protection is None:
        assert _gate(entry)[0] is GateKind.SEND
        assert _targets(hass) == [*before, 0]
    else:
        assert _gate(entry) == (GateKind.SUPPRESS, protection, Layer.PROTECTION)
        assert _targets(hass) == before

    # The fire opens: sent, or, where the comfort command to 100 % is still
    # under way, taken over by the fire.
    alarms.fire = True
    await recompute(hass, freezer, entry)
    _, reason, layer = _gate(entry)
    assert layer is Layer.FIRE
    assert reason in (ReasonCode.SENT, ReasonCode.MOVEMENT_TAKEN_OVER)
    assert _targets(hass)[-1] == 100  # noqa: PLR2004 - the fire opens
    assert setups.count == 1


@pytest.mark.parametrize(
    ("house", "group", "window", "expected"),
    [
        ("protection_only", "automatic", "off", ReasonCode.MODE_OFF),
        ("off", "automatic", "automatic", ReasonCode.MODE_OFF),
        ("automatic", "protection_only", "automatic", ReasonCode.MODE_PROTECTION_ONLY),
        ("automatic", "automatic", "automatic", None),
    ],
)
async def test_the_most_restrictive_mode_of_the_three_levels_applies(  # noqa: PLR0913 - three levels
    hass: HomeAssistant,
    freezer: Any,
    *,
    alarms: Alarms,
    house: str,
    group: str,
    window: str,
    expected: ReasonCode | None,
) -> None:
    """Whatever the window says, a stricter mode of the house or the group wins."""
    del alarms
    entry = await setup_house(hass, freezer)

    for level, mode in zip(LEVELS, (house, group, window), strict=True):
        await select_mode(hass, mode_of(level), mode)
    await settle(hass, freezer)

    kind, reason, _ = _gate(entry)
    if expected is None:
        assert reason not in (ReasonCode.MODE_OFF, ReasonCode.MODE_PROTECTION_ONLY)
    else:
        assert (kind, reason) == (GateKind.SUPPRESS, expected)


async def test_a_pause_of_the_house_reaches_every_window_within_the_coalescing_time(
    hass: HomeAssistant, freezer: Any, alarms: Alarms
) -> None:
    """One switch of the house, the next recompute of each window reads "paused"."""
    del alarms
    entry = await setup_house(hass, freezer)

    await turn(hass, pause_of(HOUSE), on=True)
    await settle(hass, freezer)

    assert _gate(entry)[1] is ReasonCode.PAUSED
    attributes = state_of(hass, REASON).attributes
    assert attributes["paused_by"] == [
        {"level": "global", "entity_id": None, "state": None}
    ]


async def test_a_window_that_is_paused_by_its_group_names_the_group(
    hass: HomeAssistant, freezer: Any, alarms: Alarms
) -> None:
    """The status shows which level pauses; the diagnostics show all three."""
    del alarms
    entry = await setup_house(hass, freezer)

    await turn(hass, pause_of(GROUP), on=True)
    await turn(hass, lock_of(WINDOW), on=False)
    await settle(hass, freezer)

    assert state_of(hass, REASON).attributes["paused_by"] == [
        {"level": "group", "entity_id": None, "state": None}
    ]
    report = entry.runtime_data.board.window_report(WINDOW_ID)
    assert [level["level"] for level in report["levels"]] == [
        "global",
        "group",
        "window",
    ]
    assert report["effective"] == {
        "paused": True,
        "maintenance_lock": False,
        "mode": "automatic",
        "dry_run": False,
    }


# ---------------------------------------------------------------------------
# A restart
# ---------------------------------------------------------------------------


async def _restart(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Stop the entry and start it again, as a restart of Home Assistant does."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_pause_lock_and_mode_keep_their_values_over_a_reload(
    hass: HomeAssistant, freezer: Any, alarms: Alarms
) -> None:
    """Pause, lock and mode of every level are what they were before."""
    del alarms
    entry = await setup_house(hass, freezer)
    await turn(hass, pause_of(HOUSE), on=True)
    await turn(hass, lock_of(GROUP), on=True)
    await select_mode(hass, mode_of(WINDOW), "off")
    # A window without a controller keeps the value it had, too.
    runtime_of(entry).async_remove_window(WINDOW_ID)
    await hass.async_block_till_done()

    await _restart(hass, entry)
    await settle(hass, freezer)

    assert state_of(hass, pause_of(HOUSE)).state == STATE_ON
    assert state_of(hass, lock_of(GROUP)).state == STATE_ON
    assert state_of(hass, mode_of(WINDOW)).state == "off"
    assert state_of(hass, pause_of(WINDOW)).state == STATE_OFF
    assert _gate(entry)[1] is ReasonCode.MAINTENANCE_LOCK


async def test_a_restart_restores_the_controls_before_the_first_decision(
    hass: HomeAssistant, freezer: Any, alarms: Alarms
) -> None:
    """What Home Assistant stored at its stop: the lock holds from the first decision.

    The value is read from the extra data the control stored, also when the
    entity was unavailable at the stop; a state without extra data is read
    too; a value that is none of the control's is dropped for its default.
    """
    del alarms
    mock_restore_cache_with_extra_data(
        hass,
        [
            (State(lock_of(WINDOW), STATE_UNAVAILABLE), {"value": True}),
            (State(mode_of(GROUP), STATE_UNAVAILABLE), {"value": "protection_only"}),
            (State(pause_of(GROUP), "sometimes"), {"value": "yes"}),
            (State(mode_of(WINDOW), STATE_UNAVAILABLE), {"value": "sideways"}),
            # Stored without extra data: the state itself is read.
            (State(pause_of(HOUSE), STATE_ON), {}),
        ],
    )
    entry = await setup_house(hass, freezer)

    assert state_of(hass, lock_of(WINDOW)).state == STATE_ON
    assert state_of(hass, pause_of(HOUSE)).state == STATE_ON
    assert state_of(hass, mode_of(GROUP)).state == "protection_only"

    assert state_of(hass, pause_of(GROUP)).state == STATE_OFF
    assert state_of(hass, mode_of(WINDOW)).state == "automatic"
    # The first decision already saw the lock: the half-open cover was not moved.
    assert _gate(entry)[1] is ReasonCode.MAINTENANCE_LOCK
    assert cover_calls(hass) == []


async def test_without_a_stored_state_the_controls_are_off_off_and_automatic(
    hass: HomeAssistant, freezer: Any, alarms: Alarms
) -> None:
    """Nothing to restore: the window runs as it did before the controls existed."""
    del alarms
    entry = await setup_house(hass, freezer)

    assert _gate(entry) == (GateKind.SEND, ReasonCode.SENT, Layer.SCHEDULE)
    assert _targets(hass) == [100]


# ---------------------------------------------------------------------------
# A group reference that cannot be read
# ---------------------------------------------------------------------------


async def _unreadable_group(
    hass: HomeAssistant, freezer: Any, *, with_group: bool
) -> MockConfigEntry:
    register_cover_services(hass)
    set_cover(hass, COVER, position=HALF_OPEN, state="open")
    groups = (
        [subentry_data(SUBENTRY_GROUP, "Example group", {CONF_SETTINGS: {}}, GROUP_ID)]
        if with_group
        else []
    )
    entry = await setup_entry(
        hass,
        {CONF_SETTINGS: FIXED_ROUTINE},
        subentries=[
            *groups,
            window_subentry(data=window_data() | {CONF_GROUP_ID: None}),
        ],
    )
    await settle(hass, freezer)
    return entry


async def test_a_window_whose_group_cannot_be_read_takes_the_strictest_group(
    hass: HomeAssistant, freezer: Any, alarms: Alarms
) -> None:
    """Nobody knows which group applies, so a lock of any group holds the window.

    The comfort functions of the window are suspended by the fault anyway;
    the stub storm shows that the lock holds protection back.
    """
    entry = await _unreadable_group(hass, freezer, with_group=True)

    await turn(hass, lock_of(GROUP), on=True)
    await turn(hass, pause_of(GROUP), on=True)
    await select_mode(hass, mode_of(GROUP), "off")
    alarms.storm = True
    await recompute(hass, freezer, entry)

    assert _gate(entry) == (
        GateKind.SUPPRESS,
        ReasonCode.MAINTENANCE_LOCK,
        Layer.PROTECTION,
    )
    assert entry.runtime_data.board.window_report(WINDOW_ID)["effective"] == {
        "paused": True,
        "maintenance_lock": True,
        "mode": "off",
        "dry_run": False,
    }
    # Nobody can see whether the group named a pause entity either, so the
    # window level inherits a blind one.
    assert state_of(hass, REASON).attributes["paused_by"] == [
        {"level": "group", "entity_id": None, "state": None},
        {"level": "window", "entity_id": None, "state": "blind"},
    ]


async def test_a_window_whose_group_cannot_be_read_without_any_group(
    hass: HomeAssistant, freezer: Any, alarms: Alarms
) -> None:
    """No group at all: the group level is neutral; the house still applies."""
    del alarms
    entry = await _unreadable_group(hass, freezer, with_group=False)

    board = entry.runtime_data.board
    report = board.window_report(WINDOW_ID)
    assert [level["level"] for level in report["levels"]] == ["global", "window"]
    assert report["paused_by"] == [
        {"level": "window", "entity_id": None, "state": "blind"}
    ]
    await turn(hass, pause_of(HOUSE), on=True)
    await settle(hass, freezer)
    assert board.pause_causes(WINDOW_ID)[0].level.value == "global"
