"""The runtime fed to the movement tracker: observe, elapse, wake-ups, after_send.

The fake covers of these tests report what the profiles of the time-lapse
simulation report: a live platform (a transit state and the position during
the travel), a platform that reports the position only at the end, and a
member that never reports. Nothing moves by itself: after a command the test
writes the reports a cover of that profile would write.

Time is controlled by the ``freezer`` fixture; no test sleeps.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import Context, Event, HomeAssistant, callback
from homeassistant.util.hass_dict import HassKey

from custom_components.roller_shutter_suite.const import EVENT_REASON
from custom_components.roller_shutter_suite.core.arbiter import member_expectation_end
from custom_components.roller_shutter_suite.core.model import (
    MemberState,
    MemberTracking,
    MovementState,
    Observation,
    OwnCommand,
    Position,
    PositionOwner,
    PositionReference,
    TrackerPhase,
    TravelDirection,
    WindowState,
    WishClass,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from custom_components.roller_shutter_suite.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.roller_shutter_suite.storage import storage_of
from tests.ha.helpers import set_cover
from tests.ha.runtime_kit import (
    COVER,
    FIXED_ROUTINE,
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
from tests.ha.status_kit import OVERRIDE, REASON, state_of

_monday_morning = pytest.fixture(autouse=True)(monday_morning)

LEFT = "cover.example_left"
RESUME = "button.example_window_resume_automation"
RIGHT = "cover.example_right"


TRACKER_EVENTS: HassKey[list[dict[str, Any]]] = HassKey("test_tracker_events")


@pytest.fixture(autouse=True)
def _tracker_events(hass: HomeAssistant) -> None:
    """Collect the reason events of the tracker and the dams, as they reach the bus."""
    fired: list[dict[str, Any]] = []
    hass.data[TRACKER_EVENTS] = fired

    @callback
    def _collect(event: Event) -> None:
        if event.data["layer"] is None:
            fired.append(dict(event.data))

    hass.bus.async_listen(EVENT_REASON, _collect)


def tracker_events(entry: Any) -> list[dict[str, Any]]:
    """Return the data of the tracker's events on the bus since the last look."""
    fired = entry.runtime_data.runtime.hass.data[TRACKER_EVENTS]
    taken = list(fired)
    fired.clear()
    return taken


def codes(entry: Any) -> list[ReasonCode]:
    """Return the codes of the tracker's events on the bus since the last look."""
    return [ReasonCode(event["reason"]) for event in tracker_events(entry)]


def gate_reason(entry: Any) -> ReasonCode | None:
    """Return the reason of the gate of the last decision."""
    decision = controller_of(entry).status.decision
    assert decision is not None
    return None if decision.gate is None else decision.gate.reason


async def armed_at(
    hass: HomeAssistant, freezer: Any, position: int, **kwargs: Any
) -> Any:
    """Set an armed window up whose cover stands at ``position`` in the day."""
    set_cover(hass, COVER, position=position)
    entry = await setup_window(hass, covers_present=False, freezer=freezer, **kwargs)
    codes(entry)
    return entry


# ---------------------------------------------------------------------------
# A movement by hand
# ---------------------------------------------------------------------------


async def test_a_hand_movement_arms_the_override_and_nothing_is_sent_until_it_ends(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The day position stands; a person lowers the shutter; the window holds still."""
    entry = await armed_at(hass, freezer, 100)
    assert commands_sent(entry) == []

    set_cover(hass, COVER, position=100, state="closing")
    await settle(hass, freezer)
    assert codes(entry) == [
        ReasonCode.MANUAL_DETECTED,
        ReasonCode.MANUAL_DETECTED_MEMBER,
        ReasonCode.OVERRIDE_STARTED,
    ]
    set_cover(hass, COVER, position=40, state="open")
    await settle(hass, freezer, seconds=5)

    state = controller_of(entry).state
    assert state.owner is PositionOwner.USER
    assert state.manual_override is not None
    assert state.manual_override.remembered_position == Position(40)
    assert gate_reason(entry) is ReasonCode.MANUAL_OVERRIDE
    assert codes(entry) == []
    # The entity follows the dam; the reason says until when and what.
    assert state_of(hass, OVERRIDE).state == STATE_ON
    reason = state_of(hass, REASON)
    assert reason.state == "manual_override"
    dam = dict(reason.attributes["manual_override"])
    assert datetime.fromisoformat(dam.pop("armed_at")) < local(10, 1)
    assert dam == {
        "end_rule": "next_part_of_day",
        "ends_at": local(20, 0).astimezone(UTC).isoformat(),
        "remembered_position": 40,
    }
    assert reason.attributes["person_at_window"] is None

    # The day goes on; the window sends nothing until the evening ends the dam.
    await advance(hass, freezer, local(19, 59))
    assert commands_sent(entry) == []
    await advance(hass, freezer, local(20, 0, second=30))
    assert ReasonCode.OVERRIDE_ENDED in codes(entry)
    assert [call.target.value for call in commands_sent(entry)] == [0]
    assert state_of(hass, OVERRIDE).state == STATE_OFF
    assert state_of(hass, REASON).attributes["manual_override"] is None


async def test_resume_automation_ends_the_override_and_the_window_moves(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The button of the window: the override ends at once, the window recomputes."""
    entry = await armed_at(hass, freezer, 100)
    set_cover(hass, COVER, position=100, state="closing")
    set_cover(hass, COVER, position=40, state="open")
    await settle(hass, freezer, seconds=5)
    codes(entry)
    assert state_of(hass, OVERRIDE).state == STATE_ON
    assert commands_sent(entry) == []

    await hass.services.async_call(
        "button", "press", {"entity_id": RESUME}, blocking=True
    )
    await settle(hass, freezer)

    assert codes(entry) == [ReasonCode.OVERRIDE_ENDED]
    assert state_of(hass, OVERRIDE).state == STATE_OFF
    assert controller_of(entry).state.manual_override is None
    assert [call.target.value for call in commands_sent(entry)] == [100]

    # Without an override the button changes nothing.
    await hass.services.async_call(
        "button", "press", {"entity_id": RESUME}, blocking=True
    )
    await settle(hass, freezer)
    assert codes(entry) == []
    assert len(commands_sent(entry)) == 1


async def test_the_button_is_unavailable_while_the_window_has_no_controller(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Pressed without a controller, it does nothing."""
    entry = await armed_at(hass, freezer, 100)
    runtime = entry.runtime_data.runtime
    controller = runtime.windows.pop(WINDOW_ID)
    try:
        button = next(
            entity
            for entity in hass.data["entity_components"]["button"].entities
            if entity.entity_id == RESUME
        )
        assert button.available is False
        await button.async_press()
    finally:
        runtime.windows[WINDOW_ID] = controller
    assert commands_sent(entry) == []


async def test_the_daily_count_is_in_the_diagnostics_and_reported_once_above_it(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Threshold 1: the second comfort movement of the day is reported, once."""
    set_cover(hass, COVER, position=50)
    entry = await setup_window(
        hass,
        house=FIXED_ROUTINE | {"comfort_movements_threshold": 1},
        covers_present=False,
        freezer=freezer,
    )
    set_cover(hass, COVER, position=100)
    await settle(hass, freezer, seconds=5)
    assert codes(entry) == []

    await advance(hass, freezer, local(20, 0, second=1))
    raised = tracker_events(entry)
    assert [(e["reason"], e["count"], e["threshold"]) for e in raised] == [
        ("comfort_movements_threshold", 2, 1)
    ]
    set_cover(hass, COVER, position=0, state="closed")
    await settle(hass, freezer, seconds=5)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    tracking = diagnostics["windows"][0]["status"]["movement_tracking"]
    assert tracking["comfort_movements"] == {
        "day": "2026-09-21",
        "count": 2,
        "reported": True,
        "threshold": 1,
    }
    (member,) = tracking["members"]
    assert member["movement_detection"] == "active"
    assert member["reporting_kind"] == "event_driven"
    assert member["reporting_time"] == 0
    assert member["travel_time_up"] == 60  # noqa: PLR2004
    assert member["latency_ms"]["count"] == 2  # noqa: PLR2004
    assert codes(entry) == []


async def test_one_member_moved_by_hand_holds_the_whole_window(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Decision 8: one dam for the window, the other member stays where it is."""
    set_cover(hass, LEFT, position=100)
    set_cover(hass, RIGHT, position=100)
    entry = await setup_window(
        hass, window_data([LEFT, RIGHT]), covers_present=False, freezer=freezer
    )
    codes(entry)

    set_cover(hass, LEFT, position=100, state="closing")
    set_cover(hass, LEFT, position=30, state="open")
    await settle(hass, freezer, seconds=5)

    assert codes(entry) == [
        ReasonCode.MANUAL_DETECTED,
        ReasonCode.MANUAL_DETECTED_MEMBER,
        ReasonCode.OVERRIDE_STARTED,
    ]
    assert controller_of(entry).state.manual_override is not None
    await advance(hass, freezer, local(19, 0))
    assert commands_sent(entry) == []
    await advance(hass, freezer, local(20, 0, second=30))
    assert sorted(call.member_id for call in commands_sent(entry)) == [LEFT, RIGHT]


async def test_the_user_of_a_dashboard_is_a_hint_on_the_member_event(
    hass: HomeAssistant, freezer: Any, hass_admin_user: Any
) -> None:
    """The user in the context of the report is kept; it decides nothing."""
    entry = await armed_at(hass, freezer, 100)
    context = Context(user_id=hass_admin_user.id)
    hass.states.async_set(
        COVER,
        "closing",
        {"supported_features": 15, "current_position": 100},
        context=context,
    )
    await settle(hass, freezer)
    events = tracker_events(entry)
    member = next(e for e in events if e["reason"] == "manual_detected_member")
    assert member["user_id"] == hass_admin_user.id
    assert member["member_id"] == COVER
    # Detected at its start, under way: no position yet (ruling of C06).
    assert member["position"] is None
    assert member["dry_run"] is False


# ---------------------------------------------------------------------------
# An own command, followed to its end
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reports",
    [
        [("opening", 60), ("opening", 80), ("open", 100)],
        [("opening", 50), ("open", 100)],
    ],
    ids=["live", "end_only"],
)
async def test_an_own_command_is_followed_to_its_end_without_a_hand_movement(
    hass: HomeAssistant, freezer: Any, reports: list[tuple[str, int]]
) -> None:
    """The integration's own movement never looks like a person's."""
    entry = await armed_at(hass, freezer, 50)
    assert [call.target.value for call in commands_sent(entry)] == [100]
    member = controller_of(entry).state.member_state(COVER)
    assert member.tracking.phase is TrackerPhase.EXPECTING

    for state, position in reports:
        freezer.tick(timedelta(seconds=10))
        set_cover(hass, COVER, position=position, state=state)
        await settle(hass, freezer)
    await settle(hass, freezer, seconds=5)

    member = controller_of(entry).state.member_state(COVER)
    assert member.tracking == MemberTracking()
    assert controller_of(entry).state.manual_override is None
    assert controller_of(entry).state.owner is not PositionOwner.USER
    assert codes(entry) == []
    assert len(commands_sent(entry)) == 1


async def test_a_stop_in_mid_travel_says_the_position_may_be_inaccurate_once(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Somebody stopped the own movement: external, and the reference is uncertain."""
    entry = await armed_at(hass, freezer, 50)
    set_cover(hass, COVER, position=60, state="opening")
    await settle(hass, freezer)
    set_cover(hass, COVER, position=70, state="open")
    await settle(hass, freezer, seconds=5)

    raised = codes(entry)
    assert raised.count(ReasonCode.POSITION_MAY_BE_INACCURATE) == 1
    assert ReasonCode.MANUAL_DETECTED in raised
    member = controller_of(entry).state.member_state(COVER)
    assert member.position_reference is PositionReference.UNCERTAIN
    await advance(hass, freezer, local(12, 0))
    assert ReasonCode.POSITION_MAY_BE_INACCURATE not in codes(entry)


# ---------------------------------------------------------------------------
# The wake-ups of the tracker
# ---------------------------------------------------------------------------


async def test_a_member_that_never_reports_reads_no_reaction_once_at_its_deadline(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The timer of the controller fires ``elapse`` at the deadline; no dam."""
    entry = await armed_at(hass, freezer, 50)
    controller = controller_of(entry)
    member = controller.state.member_state(COVER)
    command = member.last_own_command
    assert command is not None
    config = next(m for m in controller.config.members if m.member_id == COVER)
    deadline = member_expectation_end(config, command)
    wake_up = controller.status.wake_up
    assert wake_up is not None
    assert wake_up.at == deadline

    await advance(hass, freezer, deadline - timedelta(seconds=2))
    assert codes(entry) == []
    await advance(hass, freezer, deadline + timedelta(seconds=1))
    assert codes(entry) == [ReasonCode.ACTUATOR_NO_REACTION]
    assert controller.state.manual_override is None
    assert controller.state.person_at_window is None

    # Later the window sends again (the cover still stands at 50); every
    # command whose deadline has passed reads "no reaction" exactly once.
    sent_before = len(commands_sent(entry))
    await advance(hass, freezer, deadline + timedelta(minutes=20))
    resent = len(commands_sent(entry)) - sent_before
    assert resent >= 1
    last = controller.state.member_state(COVER).last_own_command
    assert last is not None
    now = controller.clock.now()
    judged = resent if member_expectation_end(config, last) <= now else resent - 1
    assert codes(entry) == [ReasonCode.ACTUATOR_NO_REACTION] * judged
    assert controller.state.manual_override is None


# ---------------------------------------------------------------------------
# The leftover of 0.2.0
# ---------------------------------------------------------------------------


def _stale(member_id: str, *, observed: bool, at: datetime) -> MemberState:
    """Return a member that expects an old own command to 100."""
    command = OwnCommand(
        command_id="old-command",
        target=Position(100),
        direction=TravelDirection.UP,
        time=at,
        wish_class=WishClass.COMFORT,
        reason=ReasonCode.SCHEDULE_DAY,
    )
    return MemberState(
        member_id,
        last_own_command=command,
        last_observation=(
            Observation(MovementState.RESTING, Position(50)) if observed else None
        ),
        tracking=MemberTracking(
            phase=TrackerPhase.EXPECTING, command_id=command.command_id
        ),
    )


@pytest.mark.parametrize(
    ("minutes_ago", "cover_at", "kept", "no_reactions"),
    [(1, 100, False, 0), (1, 50, True, 2), (180, 100, False, 0), (180, 50, False, 1)],
    ids=["fresh-at-target", "fresh-elsewhere", "old-at-target", "old-elsewhere"],
)
async def test_a_stale_expectation_of_0_2_0_raises_nothing_and_arms_no_dam(  # noqa: PLR0913 - the case and its expected outcome
    hass: HomeAssistant,
    freezer: Any,
    minutes_ago: int,
    cover_at: int,
    *,
    kept: bool,
    no_reactions: int,
) -> None:
    """A phase ``expecting`` without an observation predates the wiring.

    Expired, or its cover at the target already: idle, and nothing is
    judged. Still within its deadline with the cover at rest elsewhere
    (from the re-review): the expectation is kept from what the cover
    reports now, so the cover that never moves reads "no reaction" once for
    the old command, and once for the command the window sends after it.
    No case arms a dam.
    """
    at = local(10, 0) - timedelta(minutes=minutes_ago)
    stored = WindowState(members=(_stale(COVER, observed=False, at=at),))
    storage_of(hass).save_window_state(WINDOW_ID, stored.to_data())
    set_cover(hass, COVER, position=cover_at)
    entry = await setup_window(hass, covers_present=False, freezer=freezer)

    controller = controller_of(entry)
    assert codes(entry) == []
    assert controller.state.manual_override is None
    assert controller.state.person_at_window is None
    member = controller.state.member_state(COVER)
    assert (member.tracking.command_id == "old-command") is kept
    assert member.tracking.before_gap is None

    for minute in range(1, 6):
        await advance(hass, freezer, local(10, minute))
    # Nothing wrong is sent: at the day target nothing, elsewhere the day target.
    expected = [] if cover_at == 100 else [100]  # noqa: PLR2004
    assert [call.target.value for call in commands_sent(entry)] == expected
    assert codes(entry) == [ReasonCode.ACTUATOR_NO_REACTION] * no_reactions
    assert controller.state.manual_override is None
    assert controller.state.person_at_window is None


@pytest.mark.parametrize("starts", [True, False], ids=["late-start", "never-moves"])
async def test_a_0_2_0_command_whose_cover_rests_at_the_start_is_followed(
    hass: HomeAssistant, freezer: Any, *, starts: bool
) -> None:
    """The case of the re-review: the command is 5 s old, the cover reports late.

    The cover is stated with a reporting time of 30 s and still rests at the
    start. Its late "opening" is the own movement, not a person's; a cover
    that never moves reads "no reaction" at the deadline, and no dam is armed.
    """
    at = local(10, 0) - timedelta(seconds=5)
    stored = WindowState(members=(_stale(COVER, observed=False, at=at),))
    storage_of(hass).save_window_state(WINDOW_ID, stored.to_data())
    set_cover(hass, COVER, position=50)
    members = {COVER: {"reporting_kind": "event_driven", "reporting_time": 30}}
    entry = await setup_window(
        hass, window_data(members=members), covers_present=False, freezer=freezer
    )
    controller = controller_of(entry)
    assert controller.state.member_state(COVER).tracking.command_id == "old-command"

    if starts:
        freezer.tick(timedelta(seconds=20))
        set_cover(hass, COVER, position=50, state="opening")
        await settle(hass, freezer)
        freezer.tick(timedelta(seconds=30))
        set_cover(hass, COVER, position=100, state="open")
        await settle(hass, freezer, seconds=5)
        assert codes(entry) == []
        assert controller.state.member_state(COVER).tracking == MemberTracking()
    else:
        config = controller.config.members[0]
        command = controller.state.member_state(COVER).last_own_command
        assert command is not None
        deadline = member_expectation_end(config, command)
        await advance(hass, freezer, deadline + timedelta(seconds=1))
        assert codes(entry) == [ReasonCode.ACTUATOR_NO_REACTION]
    assert controller.state.manual_override is None
    assert controller.state.person_at_window is None
    assert ReasonCode.OVERRIDE_STARTED not in codes(entry)


async def test_a_would_be_command_of_an_unstated_cover_does_not_hold_the_evening(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The reviewer's case: a would-be command at 19:55 and the evening at 20:00.

    The reporting time of the cover is not stated. The simulated command
    counts without it (decision of the orchestrator), so the evening is
    recorded at 20:00 as an armed window would send it, not deferred as
    "movement in flight" until about 20:06.
    """
    freezer.move_to(local(19, 55))
    set_cover(hass, COVER, position=50)
    entry = await setup_window(
        hass,
        window_data(dry_run=True, members={}),
        covers_present=False,
        freezer=freezer,
    )
    controller = controller_of(entry)
    assert controller.config.members[0].capabilities.reporting_time is None
    simulated = controller.state.simulated
    assert simulated is not None
    assert [c.command.target for c in simulated.commands] == [Position(100)]

    await advance(hass, freezer, local(20, 0, second=1))
    decision = controller.status.decision
    assert decision is not None
    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.DRY_RUN
    assert decision.target == Position(0)
    assert commands_sent(entry) == []


@pytest.mark.parametrize(
    ("state", "dammed"),
    [("opening", False), ("closing", True)],
    ids=["towards-the-target", "against-it"],
)
async def test_a_stale_expectation_whose_cover_still_travels_is_the_own_movement(
    hass: HomeAssistant, freezer: Any, state: str, *, dammed: bool
) -> None:
    """From the review: 20 s after a command of 0.2.0 the cover still moves at the start.

    The command is real and its deadline lies ahead, so the expectation is
    kept: a movement towards its target is the own movement, one against it
    is somebody reversing it.
    """
    at = local(10, 0) - timedelta(seconds=20)
    stored = WindowState(members=(_stale(COVER, observed=False, at=at),))
    storage_of(hass).save_window_state(WINDOW_ID, stored.to_data())
    set_cover(hass, COVER, position=50, state=state)
    entry = await setup_window(hass, covers_present=False, freezer=freezer)
    set_cover(hass, COVER, position=100 if not dammed else 20, state="open")
    await settle(hass, freezer, seconds=5)

    raised = codes(entry)
    controller = controller_of(entry)
    assert (ReasonCode.MANUAL_DETECTED in raised) is dammed
    assert (controller.state.person_at_window is not None) is dammed
    assert ReasonCode.ACTUATOR_NO_REACTION not in raised
    if not dammed:
        assert raised == []
        assert controller.state.member_state(COVER).tracking == MemberTracking()
        assert commands_sent(entry) == []


@pytest.mark.parametrize(
    ("cover_at", "dammed"),
    [(50, False), (100, False), (20, True)],
    ids=["as-seen", "at-the-target", "elsewhere"],
)
async def test_an_expectation_whose_deadline_passed_before_the_start_is_a_gap(
    hass: HomeAssistant, freezer: Any, cover_at: int, *, dammed: bool
) -> None:
    """Observed, but its deadline lies in the past at the start: idle, no event.

    What happened while no controller ran is judged like the return from an
    unavailable gap: the cover where it was seen or at the target of the own
    command is nothing; anywhere else somebody moved it meanwhile.
    """
    stored = WindowState(members=(_stale(COVER, observed=True, at=local(9, 0)),))
    storage_of(hass).save_window_state(WINDOW_ID, stored.to_data())
    set_cover(hass, COVER, position=cover_at)
    entry = await setup_window(hass, covers_present=False, freezer=freezer)
    await settle(hass, freezer, seconds=5)

    raised = codes(entry)
    assert ReasonCode.ACTUATOR_NO_REACTION not in raised
    assert ReasonCode.MOVEMENT_NOT_FINISHED not in raised
    assert (ReasonCode.MOVED_DURING_DOWNTIME in raised) is dammed
    # Before the first decision nobody knows whether protection wins: the
    # person-at-the-window dam (ruling of the project owner for block C06).
    assert (controller_of(entry).state.person_at_window is not None) is dammed
