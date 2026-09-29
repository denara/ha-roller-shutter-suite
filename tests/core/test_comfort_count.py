"""The daily count of own comfort movements (E10, gate rule 9).

A movement counts when it is sent as comfort, however many members it
addresses; a take-over counts nothing; protection and fire never count; the
completion of a command for a member that returns counts nothing. The count
starts again at the local day change, and above the threshold (default 40)
one event per day reports it, with the count and the threshold as
attributes (``comfort_movements_threshold``). It blocks nothing.
"""

from collections.abc import Mapping
from dataclasses import replace
from datetime import date, timedelta

from custom_components.roller_shutter_suite.core.engine import Engine, build_arbiter
from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    AnySourceValue,
    ComfortMovementCount,
    MemberState,
    MissedCommand,
    OwnCommand,
    TravelDirection,
    WindowState,
    WishClass,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import (
    LEFT,
    NOW,
    RIGHT,
    STUB_LAYERS,
    day,
    fire,
    night,
    observed,
    snapshot,
    storm,
    window,
)
from tests.core.tracking_kit import codes

TODAY = NOW.date()
IDS = {LEFT: "command-left", RIGHT: "command-right"}


def _engine(**changes: object) -> Engine:
    return Engine(window(LEFT, RIGHT, **changes), build_arbiter(STUB_LAYERS))


def _world(
    sources: Mapping[str, AnySourceValue], state: WindowState | None = None
) -> WorldSnapshot:
    return snapshot(
        sources=sources,
        observation=observed(left=0, right=0),
        state=WindowState() if state is None else state,
    )


def test_a_comfort_send_counts_one_movement_whatever_the_number_of_members() -> None:
    """Two members addressed, one movement of the window."""
    world = _world(day())
    engine = _engine()
    decision = engine.recompute(world)

    state = engine.state_after_send(world, decision, IDS)

    assert decision.addressed == (LEFT, RIGHT)
    assert state.comfort_movements == ComfortMovementCount(TODAY, 1)


def test_protection_and_fire_never_count() -> None:
    """Only comfort movements count."""
    engine = _engine()
    for sources in (storm(), fire()):
        world = snapshot(
            sources=sources,
            observation=observed(left=50, right=50),
            state=WindowState(),
        )
        decision = engine.recompute(world)
        state = engine.state_after_send(world, decision, IDS)
        assert decision.winning_wish is not None
        assert decision.winning_wish.wish_class is not WishClass.COMFORT
        assert state.comfort_movements is None


def test_a_take_over_counts_nothing() -> None:
    """The comfort movement was counted when it was sent; the take-over sends nothing."""
    engine = _engine()
    closing = snapshot(
        sources=night(), observation=observed(left=100, right=100), state=WindowState()
    )
    sent = engine.state_after_send(closing, engine.recompute(closing), IDS)
    assert sent.comfort_movements == ComfortMovementCount(TODAY, 1)
    world = replace(
        closing,
        sources=storm(),
        observation=observed(left="down:80", right="down:80"),
        state=sent,
        time=NOW + timedelta(seconds=3),
    )

    decision = engine.recompute(world)
    after = engine.state_after(world, decision)

    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.MOVEMENT_TAKEN_OVER
    assert after.comfort_movements == sent.comfort_movements


def test_the_completion_of_a_missed_command_counts_nothing() -> None:
    """The return of a member is no fresh wish, and no new movement of the day."""
    earlier = NOW - timedelta(minutes=3)
    missed = MissedCommand(
        FULLY_CLOSED, WishClass.COMFORT, ReasonCode.SCHEDULE_NIGHT, earlier
    )
    state = WindowState(
        members=(
            MemberState(LEFT, missed_command=missed),
            MemberState(
                RIGHT,
                last_own_command=OwnCommand(
                    "command-earlier",
                    FULLY_CLOSED,
                    TravelDirection.DOWN,
                    earlier,
                    WishClass.COMFORT,
                    ReasonCode.SCHEDULE_NIGHT,
                ),
                command_attempts=1,
                last_attempt_at=earlier,
            ),
        ),
        last_comfort_movement=earlier,
        comfort_movements=ComfortMovementCount(TODAY, 7),
    )
    world = snapshot(
        sources=night(), observation=observed(left=100, right=0), state=state
    )
    engine = _engine()
    decision = engine.recompute(world)

    after = engine.after_send(world, decision, {LEFT: "command-left"})

    assert decision.completes_command
    assert after.state.comfort_movements == ComfortMovementCount(TODAY, 7)
    assert after.events == ()


def test_the_count_starts_again_on_a_new_local_day() -> None:
    """Yesterday's movements do not count today."""
    engine = _engine()
    yesterday = WindowState(
        comfort_movements=ComfortMovementCount(
            TODAY - timedelta(days=1), 41, reported=True
        )
    )
    world = _world(day(), yesterday)

    state = engine.state_after_send(world, engine.recompute(world), IDS)

    assert state.comfort_movements == ComfortMovementCount(TODAY, 1)


def test_above_the_threshold_the_count_is_reported_once_a_day() -> None:
    """The 41st movement with the default threshold of 40; not the 42nd; blocks nothing."""
    engine = _engine()
    forty = WindowState(comfort_movements=ComfortMovementCount(TODAY, 40))
    world = _world(day(), forty)
    decision = engine.recompute(world)

    reported = engine.after_send(world, decision, IDS)
    # Another movement later that day: only the count is carried over.
    later = WindowState(comfort_movements=reported.state.comfort_movements)
    again_world = _world(day(), later)
    again = engine.after_send(again_world, engine.recompute(again_world), IDS)

    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.SENT
    assert codes(reported.events) == [ReasonCode.COMFORT_MOVEMENTS_THRESHOLD]
    assert reported.events[0].count == 41  # noqa: PLR2004 - one above the default
    assert reported.events[0].threshold == 40  # noqa: PLR2004 - the default
    assert reported.state.comfort_movements == ComfortMovementCount(
        TODAY, 41, reported=True
    )
    assert again.events == ()
    assert again.state.comfort_movements == ComfortMovementCount(
        TODAY, 42, reported=True
    )


def test_the_threshold_is_a_setting() -> None:
    """With a threshold of 3 the fourth movement is reported."""
    engine = _engine(comfort_movements_threshold=3)
    three = WindowState(comfort_movements=ComfortMovementCount(TODAY, 3))
    world = _world(day(), three)

    reported = engine.after_send(world, engine.recompute(world), IDS)

    assert codes(reported.events) == [ReasonCode.COMFORT_MOVEMENTS_THRESHOLD]
    assert reported.events[0].threshold == 3  # noqa: PLR2004 - the setting


def test_a_decision_that_did_not_send_counts_nothing() -> None:
    """The count follows sends, not decisions."""
    engine = _engine()
    world = snapshot(
        sources=day(), observation=observed(left=100, right=100), state=WindowState()
    )

    after = engine.after_send(world, engine.recompute(world), IDS)

    assert after.state is world.state
    assert after.events == ()


def test_the_count_goes_through_plain_data_and_is_optional() -> None:
    """Persisted with the window state; data written before it existed reads as none."""
    state = WindowState(comfort_movements=ComfortMovementCount(date(2026, 1, 15), 3))
    data = state.to_data()

    assert WindowState.from_data(data) == state
    del data["comfort_movements"]
    assert WindowState.from_data(data) == WindowState()
