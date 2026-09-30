"""The runtime fed to the movement tracker: observe, elapse, wake-ups, after_send.

The fake covers of these tests report what the profiles of the time-lapse
simulation report: a live platform (a transit state and the position during
the travel), a platform that reports the position only at the end, and a
member that never reports. Nothing moves by itself: after a command the test
writes the reports a cover of that profile would write.

Time is controlled by the ``freezer`` fixture; no test sleeps.
"""

from datetime import datetime, timedelta
from typing import Any

import pytest
from homeassistant.core import Context, HomeAssistant

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
from custom_components.roller_shutter_suite.storage import storage_of
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

_monday_morning = pytest.fixture(autouse=True)(monday_morning)

LEFT = "cover.example_left"
RIGHT = "cover.example_right"


def codes(entry: Any) -> list[ReasonCode]:
    """Return the codes of the tracker's events since the last look."""
    return [event.code for event in controller_of(entry).take_tracker_events()]


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

    # The day goes on; the window sends nothing until the evening ends the dam.
    await advance(hass, freezer, local(19, 59))
    assert commands_sent(entry) == []
    await advance(hass, freezer, local(20, 0, second=30))
    assert ReasonCode.OVERRIDE_ENDED in codes(entry)
    assert [call.target.value for call in commands_sent(entry)] == [0]


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
    events = controller_of(entry).take_tracker_events()
    member = next(e for e in events if e.code is ReasonCode.MANUAL_DETECTED_MEMBER)
    assert member.user_id == hass_admin_user.id


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

    await advance(hass, freezer, deadline + timedelta(minutes=20))
    assert ReasonCode.ACTUATOR_NO_REACTION not in codes(entry)[:1]


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
    ("minutes_ago", "cover_at"),
    [(1, 100), (1, 50), (180, 100), (180, 50)],
    ids=["fresh-at-target", "fresh-elsewhere", "old-at-target", "old-elsewhere"],
)
async def test_a_stale_expectation_of_0_2_0_raises_nothing_and_arms_no_dam(
    hass: HomeAssistant, freezer: Any, minutes_ago: int, cover_at: int
) -> None:
    """A phase ``expecting`` without an observation predates the wiring: idle, once.

    Its command may still count as pending for the gate until its deadline;
    then the window sends what the day wants, and the tracker says nothing
    about the old command, ever.
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
    assert member.tracking.command_id != "old-command"
    assert member.tracking.before_gap is None

    for minute in range(1, 6):
        await advance(hass, freezer, local(10, minute))
    # Nothing wrong is sent: at the day target nothing, elsewhere the day target.
    expected = [] if cover_at == 100 else [100]  # noqa: PLR2004
    assert [call.target.value for call in commands_sent(entry)] == expected
    # The fake cover never answers the new command; the old one is never judged.
    assert codes(entry) == [ReasonCode.ACTUATOR_NO_REACTION] * len(expected)
    assert controller.state.manual_override is None


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
