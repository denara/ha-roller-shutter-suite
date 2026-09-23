"""What a real send leaves behind: ``Engine.state_after_send``."""

from datetime import timedelta

import pytest

from custom_components.roller_shutter_suite.core.arbiter import (
    direction_of,
    record_sent_commands,
)
from custom_components.roller_shutter_suite.core.model import (
    Decision,
    GateKind,
    MemberState,
    OwnCommand,
    Position,
    PositionOwner,
    SourceValue,
    TravelDirection,
    WindowState,
    WishClass,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import (
    LEFT,
    NOW,
    RIGHT,
    day,
    engine,
    fire,
    night,
    observed,
    snapshot,
    window,
)

IDS = {LEFT: "command-left", RIGHT: "command-right"}


def _sent(decision: Decision) -> None:
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND


def test_a_send_records_the_command_the_owner_and_the_comfort_clock() -> None:
    """Per member the last own command with one attempt; the owner is the engine."""
    world = snapshot(sources=day(), position=0)
    decision = engine().recompute(world)
    _sent(decision)

    state = engine().state_after_send(world, decision, IDS)

    assert state.owner is PositionOwner.ENGINE
    assert state.last_comfort_movement == NOW
    (member,) = state.members
    assert member.member_id == LEFT
    assert member.command_attempts == 1
    assert member.last_attempt_at == NOW
    assert member.last_own_command == OwnCommand(
        command_id="command-left",
        target=Position(100),
        direction=TravelDirection.UP,
        time=NOW,
        wish_class=WishClass.COMFORT,
        reason=ReasonCode.SCHEDULE_DAY,
    )


def test_a_fire_send_leaves_the_comfort_clock_alone() -> None:
    """Only a comfort movement sets the motor protection clock."""
    earlier = NOW - timedelta(hours=1)
    world = snapshot(
        sources=fire(), position=0, state=WindowState(last_comfort_movement=earlier)
    )
    decision = engine().recompute(world)
    _sent(decision)

    state = engine().state_after_send(world, decision, IDS)

    assert state.last_comfort_movement == earlier
    assert state.members[0].last_own_command is not None
    assert state.members[0].last_own_command.wish_class is WishClass.FIRE
    assert state.members[0].last_own_command.reason is ReasonCode.FIRE_ALARM


def test_a_new_command_replaces_the_old_one_as_a_whole() -> None:
    """The attempts start again at one; other facts of the member stay."""
    old = OwnCommand(
        "command-old",
        Position(30),
        TravelDirection.DOWN,
        NOW - timedelta(minutes=30),
        WishClass.COMFORT,
        ReasonCode.SCHEDULE_NIGHT,
    )
    before = WindowState(
        members=(
            MemberState(
                LEFT,
                last_own_command=old,
                command_attempts=3,
                last_attempt_at=NOW - timedelta(minutes=20),
            ),
        )
    )
    world = snapshot(sources=day(), position=0, state=before)
    decision = engine().recompute(world)
    _sent(decision)

    state = engine().state_after_send(world, decision, IDS)

    (member,) = state.members
    assert member.last_own_command is not None
    assert member.last_own_command.command_id == "command-left"
    assert member.command_attempts == 1
    assert member.last_attempt_at == NOW


def test_only_members_with_an_identifier_are_recorded() -> None:
    """A member that was not commanded (no identifier) is left as it is."""
    config = window(LEFT, RIGHT)
    world = snapshot(
        sources=night(), observation=observed(left=100, right=100), state=WindowState()
    )
    decision = engine(config).recompute(world)
    _sent(decision)

    state = engine(config).state_after_send(world, decision, {LEFT: "command-left"})

    assert [m.member_id for m in state.members] == [LEFT]
    assert state.members[0].last_own_command is not None
    assert state.members[0].last_own_command.direction is TravelDirection.DOWN


def test_a_decision_that_did_not_send_leaves_the_state_alone() -> None:
    """Suppressed, deferred, or nothing at the gate: nothing is recorded."""
    reached = snapshot(sources=day(), position=100)
    decision = engine().recompute(reached)
    assert decision.gate is not None
    assert decision.gate.kind is not GateKind.SEND

    assert engine().state_after_send(reached, decision, IDS) is reached.state
    nothing = Decision(winning_wish=None)
    assert record_sent_commands(reached, nothing, IDS) is reached.state


@pytest.mark.parametrize(
    ("reported", "target", "direction"),
    [
        (20, 80, TravelDirection.UP),
        (80, 20, TravelDirection.DOWN),
        (None, 50, TravelDirection.UP),
        (None, 49, TravelDirection.DOWN),
        (50, 50, TravelDirection.UP),
    ],
)
def test_the_direction_of_a_command(
    reported: int | None, target: int, direction: TravelDirection
) -> None:
    """From the reported position to the target; without one, the halfway rule."""
    assert (
        direction_of(Position(target), None if reported is None else Position(reported))
        is direction
    )


def test_a_member_without_position_feedback_gets_a_direction_by_the_halfway_rule() -> (
    None
):
    """Sent to 100 without a reported position: upwards."""
    world = snapshot(sources=day(shading_position=SourceValue.of(100)), position=None)
    decision = engine().recompute(world)
    _sent(decision)

    state = engine().state_after_send(world, decision, IDS)

    assert state.members[0].last_own_command is not None
    assert state.members[0].last_own_command.direction is TravelDirection.UP
