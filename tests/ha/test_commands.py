"""What the runtime remembers when the gate lets a wish through."""

from datetime import UTC, datetime, timedelta

from custom_components.roller_shutter_suite.commands import (
    commands_of,
    state_with_commands,
)
from custom_components.roller_shutter_suite.core.model import (
    Controls,
    Decision,
    GateOutcome,
    GateRule,
    Layer,
    MemberObservation,
    MemberState,
    MemberTarget,
    MovementState,
    Observation,
    OwnCommand,
    Position,
    SunPosition,
    TravelDirection,
    WindowObservation,
    WindowState,
    Wish,
    WishClass,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode

NOW = datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
LEFT = "cover.example_left"
RIGHT = "cover.example_right"


def _snapshot(
    positions: dict[str, int | None], state: WindowState | None = None
) -> WorldSnapshot:
    return WorldSnapshot(
        time=NOW,
        sun=SunPosition(180.0, 30.0),
        sources={},
        observation=WindowObservation(
            tuple(
                MemberObservation(
                    member_id,
                    Observation(
                        MovementState.RESTING,
                        None if position is None else Position(position),
                    ),
                )
                for member_id, position in positions.items()
            )
        ),
        state=WindowState() if state is None else state,
        controls=Controls(dry_run=False),
    )


def _decision(
    targets: dict[str, int | None], layer: Layer = Layer.SCHEDULE, *, send: bool = True
) -> Decision:
    members = tuple(
        MemberTarget(member_id, None if position is None else Position(position))
        for member_id, position in targets.items()
    )
    # A member without a target was pinned by a constraint; the wish had one.
    wished = tuple(
        MemberTarget(member.member_id, member.position or Position(0))
        for member in members
    )
    reason = ReasonCode.FIRE_ALARM if layer is Layer.FIRE else ReasonCode.SCHEDULE_DAY
    return Decision(
        winning_wish=Wish.target_per_member(layer, reason, wished),
        targets=members,
        gate=GateOutcome.send()
        if send
        else GateOutcome.suppress(GateRule.PAUSE, ReasonCode.PAUSED),
    )


def test_a_send_gives_one_command_per_member_with_a_target() -> None:
    """Each member with a target gets its own command; a pinned member gets none."""
    commands = commands_of(
        _snapshot({LEFT: 20, RIGHT: 20}), _decision({LEFT: 80, RIGHT: None}), NOW
    )

    assert [c.member_id for c in commands] == [LEFT]
    command = commands[0].command
    assert command.target == Position(80)
    assert command.direction is TravelDirection.UP
    assert command.time == NOW
    assert command.wish_class is WishClass.COMFORT
    assert command.reason is ReasonCode.SCHEDULE_DAY
    assert command.context_id is None


def test_the_direction_follows_the_position_or_the_middle_without_one() -> None:
    """Below the current position is down; without a position 50 and above is up."""
    snapshot = _snapshot({LEFT: 80, RIGHT: None})

    down = commands_of(snapshot, _decision({LEFT: 20, RIGHT: 20}), NOW)
    up = commands_of(snapshot, _decision({LEFT: 90, RIGHT: 50}), NOW)

    assert [c.command.direction for c in down] == [
        TravelDirection.DOWN,
        TravelDirection.DOWN,
    ]
    assert [c.command.direction for c in up] == [TravelDirection.UP, TravelDirection.UP]


def test_every_command_of_a_send_has_its_own_identifier() -> None:
    """Two members, two identifiers; two sends, four."""
    snapshot = _snapshot({LEFT: 0, RIGHT: 0})
    first = commands_of(snapshot, _decision({LEFT: 100, RIGHT: 100}), NOW)
    second = commands_of(snapshot, _decision({LEFT: 100, RIGHT: 100}), NOW)

    identifiers = {c.command.command_id for c in (*first, *second)}

    assert len(identifiers) == len(first) + len(second)


def test_only_a_send_gives_commands() -> None:
    """A suppression, a deferral and a decision without a target give none."""
    snapshot = _snapshot({LEFT: 0})

    assert commands_of(snapshot, _decision({LEFT: 100}, send=False), NOW) == ()
    assert commands_of(snapshot, Decision(winning_wish=None), NOW) == ()


def test_the_state_remembers_the_commands_and_the_comfort_clock() -> None:
    """The last own command of a member is replaced; a comfort send moves the clock."""
    earlier = NOW - timedelta(hours=1)
    old = OwnCommand(
        "old",
        Position(0),
        TravelDirection.DOWN,
        earlier,
        WishClass.COMFORT,
        ReasonCode.SCHEDULE_NIGHT,
    )
    state = WindowState(
        members=(MemberState(LEFT, old, command_attempts=2, last_attempt_at=earlier),),
        last_comfort_movement=earlier,
    )
    commands = commands_of(
        _snapshot({LEFT: 0, RIGHT: 0}, state), _decision({LEFT: 100, RIGHT: 100}), NOW
    )

    after = state_with_commands(state, commands)

    assert [m.member_id for m in after.members] == [LEFT, RIGHT]
    assert after.members[0].last_own_command == commands[0].command
    assert after.members[0].command_attempts == 0
    assert after.members[0].last_attempt_at is None
    assert after.members[1].last_own_command == commands[1].command
    assert after.last_comfort_movement == NOW
    assert after.commanded_targets == {LEFT: Position(100), RIGHT: Position(100)}


def test_a_fire_command_leaves_the_comfort_clock_alone() -> None:
    """Fire and protection never count as comfort movements."""
    earlier = NOW - timedelta(hours=1)
    state = WindowState(last_comfort_movement=earlier)
    commands = commands_of(
        _snapshot({LEFT: 0}, state), _decision({LEFT: 100}, Layer.FIRE), NOW
    )

    after = state_with_commands(state, commands)

    assert after.members[0].last_own_command is not None
    assert after.members[0].last_own_command.wish_class is WishClass.FIRE
    assert after.last_comfort_movement == earlier


def test_without_commands_the_state_is_returned_as_it_is() -> None:
    """Nothing to remember, nothing changes."""
    state = WindowState()

    assert state_with_commands(state, ()) is state
