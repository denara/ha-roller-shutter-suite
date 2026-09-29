"""The core names the commanded members itself (block C06, first item).

A decision whose gate says ``send`` states which members it addresses: every
member with a target that is available and does not stand at that target
within its tolerance; a member without position feedback cannot be judged and
is addressed. ``Engine.state_after_send`` records exactly those. Two rulings of
the project owner belong to it:

- A send addresses only the members that do not stand at the target within
  tolerance; a member that already stands there gets no command and no record.
- The return of a member that was unavailable during a command is the
  completion of that command, not a fresh wish: only that member is
  addressed, with the class and the reason of the command the others
  received; it passes the minimum interval and counts no comfort movement.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.arbiter import (
    GateRuleRegistration,
    record_sent_commands,
)
from custom_components.roller_shutter_suite.core.engine import Engine, build_arbiter
from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    Decision,
    GateKind,
    GateOutcome,
    GateRule,
    Layer,
    MemberState,
    MemberTarget,
    MissedCommand,
    OwnCommand,
    Position,
    SourceValue,
    TravelDirection,
    WindowConfig,
    WindowState,
    Wish,
    WishClass,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import (
    DRY_RUN,
    LEFT,
    NOW,
    RIGHT,
    STUB_LAYERS,
    day,
    engine,
    night,
    observed,
    profile,
    since,
    snapshot,
    storm,
    window,
)

PAIR = window(LEFT, RIGHT)
IDS = {LEFT: "command-left", RIGHT: "command-right"}
EARLIER = NOW - timedelta(minutes=3)
"""The evening closing was sent three minutes ago, inside the minimum interval."""


def _decide(world: WorldSnapshot, config: WindowConfig = PAIR) -> Decision:
    return engine(config).recompute(world)


def _sent(decision: Decision) -> None:
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND


# --- The decision names the addressed members -------------------------------------


def test_a_member_that_stands_at_its_target_is_not_addressed() -> None:
    """Left stands at 0, right at 100: the evening closing addresses right only."""
    decision = _decide(
        snapshot(sources=night(), observation=observed(left=0, right=100))
    )

    _sent(decision)
    assert decision.addressed == (RIGHT,)
    assert decision.addressed_targets == ((RIGHT, FULLY_CLOSED),)


def test_a_member_within_its_tolerance_is_not_addressed() -> None:
    """A calculated position within 2 of the target stands there."""
    decision = _decide(
        snapshot(sources=night(), observation=observed(left=2, right=50))
    )

    _sent(decision)
    assert decision.addressed == (RIGHT,)


def test_an_unavailable_member_is_not_addressed() -> None:
    """Section 9: the others are commanded; the unavailable one is not."""
    decision = _decide(
        snapshot(sources=night(), observation=observed(left="unavailable", right=100))
    )

    _sent(decision)
    assert decision.addressed == (RIGHT,)


def test_a_member_without_position_feedback_is_addressed() -> None:
    """It cannot be judged; both members are commanded, in the order of the targets."""
    config = window(LEFT, RIGHT, profiles={LEFT: profile(reports_position=False)})
    decision = _decide(
        snapshot(sources=night(), observation=observed(left=None, right=100)), config
    )

    _sent(decision)
    assert decision.addressed == (LEFT, RIGHT)
    assert [member for member, _ in decision.addressed_targets] == [LEFT, RIGHT]


def test_only_a_send_names_addressed_members() -> None:
    """Target reached, a deferral, dry-run: nothing is addressed."""
    reached = _decide(snapshot(sources=night(), observation=observed(left=0, right=0)))
    dry = _decide(
        snapshot(
            sources=night(), observation=observed(left=100, right=100), controls=DRY_RUN
        )
    )

    for decision in (reached, dry):
        assert decision.gate is not None
        assert decision.gate.kind is not GateKind.SEND
        assert decision.addressed is None
        assert decision.addressed_targets == ()


# --- The recorder records exactly the addressed members ----------------------------


def test_state_after_send_records_exactly_the_addressed_members() -> None:
    """An identifier for a member that is not addressed records nothing for it."""
    world = snapshot(sources=night(), observation=observed(left=0, right=100))
    decision = _decide(world)

    state = Engine(PAIR, build_arbiter(STUB_LAYERS)).state_after_send(
        world, decision, IDS
    )

    recorded = {m.member_id: m.last_own_command for m in state.members}
    assert set(recorded) == {RIGHT}
    command = recorded[RIGHT]
    assert command is not None
    assert command.command_id == "command-right"


def test_an_unavailable_member_remembers_the_command_it_missed() -> None:
    """Target, class, reason and time of the command the others received."""
    world = snapshot(
        sources=night(), observation=observed(left="unavailable", right=100)
    )
    decision = _decide(world)

    state = engine(PAIR).state_after_send(world, decision, {RIGHT: "command-right"})

    by_member = {member.member_id: member for member in state.members}
    assert by_member[LEFT].last_own_command is None
    assert by_member[LEFT].missed_command == MissedCommand(
        FULLY_CLOSED, WishClass.COMFORT, ReasonCode.SCHEDULE_NIGHT, NOW
    )
    assert by_member[RIGHT].missed_command is None


def test_a_member_at_its_target_forgets_what_it_missed() -> None:
    """It stands where the window wants it now: nothing is left to complete."""
    missed = MissedCommand(
        FULLY_CLOSED, WishClass.COMFORT, ReasonCode.SCHEDULE_NIGHT, EARLIER
    )
    before = WindowState(members=(MemberState(LEFT, missed_command=missed),))
    world = snapshot(
        sources=night(), observation=observed(left=0, right=100), state=before
    )
    decision = _decide(world)

    state = engine(PAIR).state_after_send(world, decision, IDS)

    by_member = {member.member_id: member for member in state.members}
    assert by_member[LEFT].missed_command is None
    assert by_member[LEFT].last_own_command is None


def test_a_hand_built_send_without_addressed_members_addresses_every_target() -> None:
    """A decision that does not state its members hands every target over."""
    targets = (MemberTarget(LEFT, Position(40)), MemberTarget(RIGHT, Position(60)))
    decision = Decision(
        winning_wish=Wish.target_per_member(
            Layer.SHADING, ReasonCode.SHADING_GEOMETRIC, targets
        ),
        targets=targets,
        gate=GateOutcome.send(),
    )

    assert decision.addressed_targets == ((LEFT, Position(40)), (RIGHT, Position(60)))
    world = snapshot(sources=day(), observation=observed(left=0, right=0))
    state = record_sent_commands(world, decision, IDS)
    assert {m.member_id for m in state.members} == {LEFT, RIGHT}


def test_a_pinned_member_is_neither_addressed_nor_recorded() -> None:
    """A constraint kept the left member where it is: only the right one moves."""
    targets = (MemberTarget(LEFT, None), MemberTarget(RIGHT, Position(60)))
    decision = Decision(
        winning_wish=Wish.target(
            Layer.SHADING, ReasonCode.SHADING_GEOMETRIC, Position(60)
        ),
        targets=targets,
        gate=GateOutcome.send(),
        addressed=(RIGHT,),
    )
    world = snapshot(sources=day(), observation=observed(left=0, right=0))

    state = record_sent_commands(world, decision, IDS)

    assert decision.addressed_targets == ((RIGHT, Position(60)),)
    assert [m.member_id for m in state.members] == [RIGHT]


# --- The return of an unavailable member completes the command ---------------------


def _returned(**changes: Any) -> WorldSnapshot:
    """Left missed the evening closing three minutes ago; now it is back at 100."""
    missed = MissedCommand(
        FULLY_CLOSED, WishClass.COMFORT, ReasonCode.SCHEDULE_NIGHT, EARLIER
    )
    right_command = OwnCommand(
        "command-right-earlier",
        FULLY_CLOSED,
        TravelDirection.DOWN,
        EARLIER,
        WishClass.COMFORT,
        ReasonCode.SCHEDULE_NIGHT,
    )
    state = WindowState(
        members=(
            MemberState(LEFT, missed_command=missed),
            MemberState(
                RIGHT,
                last_own_command=right_command,
                command_attempts=1,
                last_attempt_at=EARLIER,
            ),
        ),
        last_comfort_movement=EARLIER,
    )
    arguments: dict[str, Any] = {
        "sources": night(part_of_day_since=since(EARLIER - timedelta(seconds=1))),
        "observation": observed(left=100, right=0),
        "state": state,
    }
    return snapshot(**(arguments | changes))


def test_the_returning_member_completes_the_command_inside_the_minimum_interval() -> (
    None
):
    """Not fresh and three minutes after the last movement, and still sent."""
    decision = _decide(_returned())

    _sent(decision)
    assert decision.completes_command
    assert decision.addressed == (LEFT,)


def test_without_the_missed_command_the_same_wish_waits_for_the_interval() -> None:
    """The contrast: an ordinary comfort wish that is not fresh is deferred."""
    world = _returned()
    plain = replace(
        world,
        state=replace(
            world.state,
            members=(MemberState(LEFT), world.state.members[1]),
        ),
    )

    decision = _decide(plain)

    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.MIN_INTERVAL
    assert not decision.completes_command


def test_the_completion_is_recorded_with_the_class_and_reason_of_the_missed_command() -> (
    None
):
    """No new comfort movement: the motor protection clock stays where it was."""
    world = _returned()
    decision = _decide(world)

    state = engine(PAIR).state_after_send(world, decision, {LEFT: "command-left"})

    by_member = {member.member_id: member for member in state.members}
    command = by_member[LEFT].last_own_command
    assert command is not None
    assert command.wish_class is WishClass.COMFORT
    assert command.reason is ReasonCode.SCHEDULE_NIGHT
    assert by_member[LEFT].missed_command is None
    assert state.last_comfort_movement == EARLIER
    assert by_member[RIGHT] == world.state.members[1]


def test_the_completion_keeps_what_another_absent_member_missed() -> None:
    """A third member that is still away keeps its own missed command."""
    third = "cover.example_third"
    config = window(LEFT, RIGHT, third)
    world = _returned()
    missed = world.state.members[0].missed_command
    assert missed is not None
    state = replace(
        world.state,
        members=(*world.state.members, MemberState(third, missed_command=missed)),
    )
    observation = observed(left=100, right=0)
    three = snapshot(
        sources=world.sources,
        observation=replace(
            observation,
            members=(
                *observation.members,
                replace(observed(left="unavailable").members[0], member_id=third),
            ),
        ),
        state=state,
    )

    decision = _decide(three, config)
    after = engine(config).state_after_send(three, decision, {LEFT: "command-left"})

    assert decision.completes_command
    assert decision.addressed == (LEFT,)
    by_member = {member.member_id: member for member in after.members}
    assert by_member[third].missed_command == missed


def test_a_wish_of_another_class_is_no_completion() -> None:
    """The storm closes too, but as a protection movement of its own."""
    world = _returned(sources=storm())

    decision = _decide(world)

    _sent(decision)
    assert not decision.completes_command
    assert decision.addressed == (LEFT,)
    state = engine(PAIR).state_after_send(world, decision, {LEFT: "command-left"})
    command = state.members[0].last_own_command
    assert command is not None
    assert command.wish_class is WishClass.PROTECTION


def test_a_wish_with_another_target_is_no_completion() -> None:
    """The window wants something else of the member now: a fresh wish is judged as such."""
    world = _returned(
        sources=day(part_of_day_since=since(EARLIER - timedelta(hours=9)))
    )

    decision = _decide(world)

    assert not decision.completes_command
    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.MIN_INTERVAL


def test_a_completion_needs_every_addressed_member_to_have_missed_the_command() -> None:
    """If another member has to move too, the send is an ordinary one."""
    world = _returned(observation=observed(left=100, right=100))

    decision = _decide(world)

    assert not decision.completes_command
    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.MIN_INTERVAL


def test_a_window_in_dry_run_completes_nothing() -> None:
    """It commands nothing, so it misses nothing."""
    decision = _decide(_returned(controls=DRY_RUN))

    assert not decision.completes_command
    assert decision.addressed is None


# --- A fire wish that passed a failed rule ------------------------------------------


def test_a_fire_send_past_a_failed_rule_addresses_every_member_with_a_target() -> None:
    """The failed rule may be the one that knows the members; nobody is left out."""

    def broken(_gate: object) -> None:
        raise RuntimeError("broken")

    rules = [
        registration
        for registration in build_arbiter(STUB_LAYERS).gate_rules
        if registration.rule is not GateRule.NO_MEMBER_CAN_EXECUTE
    ]
    failing = GateRuleRegistration(
        GateRule.NO_MEMBER_CAN_EXECUTE,
        frozenset(WishClass),
        broken,
        None,
    )
    arbiter = replace(build_arbiter(STUB_LAYERS), gate_rules=(*rules, failing))
    world = snapshot(
        sources=day(fire_alarm=SourceValue.of(True)),
        observation=observed(left="unavailable", right="unavailable"),
    )

    decision = arbiter.recompute(PAIR, world)

    _sent(decision)
    assert decision.addressed == (LEFT, RIGHT)


# --- The model keeps the statement consistent --------------------------------------


def _send(*addressed: str, completes: bool = False) -> Decision:
    targets = (MemberTarget(LEFT, Position(40)), MemberTarget(RIGHT, Position(60)))
    return Decision(
        winning_wish=Wish.target_per_member(
            Layer.SHADING, ReasonCode.SHADING_GEOMETRIC, targets
        ),
        targets=targets,
        gate=GateOutcome.send(),
        addressed=addressed,
        completes_command=completes,
    )


@pytest.mark.parametrize(
    ("addressed", "message"),
    [
        ((), "at least one member"),
        ((LEFT, LEFT), "unique"),
        (("cover.example_other",), "a member with a target"),
        ((RIGHT, LEFT), "in the order of the targets"),
        (("",), "must not be empty"),
    ],
)
def test_the_addressed_members_must_fit_the_targets(
    addressed: tuple[str, ...], message: str
) -> None:
    """Only members with a target, once each, in their order."""
    with pytest.raises(ValueError, match=message):
        _send(*addressed)


def test_only_a_send_addresses_members() -> None:
    """A suppression or a decision without a gate names none."""
    targets = (MemberTarget(LEFT, Position(40)),)
    wish = Wish.target(Layer.SCHEDULE, ReasonCode.SCHEDULE_DAY, Position(40))
    with pytest.raises(ValueError, match="only a decision that sends"):
        Decision(
            winning_wish=wish,
            targets=targets,
            gate=GateOutcome.suppress(GateRule.PAUSE, ReasonCode.PAUSED),
            addressed=(LEFT,),
        )
    with pytest.raises(ValueError, match="only a decision that sends"):
        Decision(
            winning_wish=wish,
            targets=(MemberTarget(LEFT, None),),
            addressed=(LEFT,),
        )


def test_a_completion_names_its_members() -> None:
    """``completes_command`` without addressed members is refused."""
    with pytest.raises(ValueError, match="names its members"):
        replace(_send(LEFT), addressed=None, completes_command=True)
    with pytest.raises(TypeError, match="completes command"):
        replace(_send(LEFT), completes_command="yes")  # type: ignore[arg-type]
    assert _send(LEFT, completes=True).completes_command


def test_a_missed_command_is_validated_and_goes_through_plain_data() -> None:
    """Round trip, a reason of the wrong group, a naive time."""
    missed = MissedCommand(
        FULLY_CLOSED, WishClass.COMFORT, ReasonCode.SCHEDULE_NIGHT, EARLIER
    )
    assert MissedCommand.from_data(missed.to_data()) == missed
    assert missed.time.tzinfo is UTC
    with pytest.raises(ValueError, match="belongs to 'gate'"):
        MissedCommand(FULLY_CLOSED, WishClass.COMFORT, ReasonCode.SENT, EARLIER)
    with pytest.raises(ValueError, match="timezone-aware"):
        MissedCommand(
            FULLY_CLOSED,
            WishClass.COMFORT,
            ReasonCode.SCHEDULE_NIGHT,
            datetime(2026, 1, 1),  # noqa: DTZ001 - the rejected case
        )
    state = MemberState(LEFT, missed_command=missed)
    assert MemberState.from_data(state.to_data()) == state


def test_member_state_written_before_the_missed_command_existed_is_read() -> None:
    """The key is optional within schema version 1; missing means nothing missed."""
    data = MemberState(LEFT).to_data()
    del data["missed_command"]

    assert MemberState.from_data(data) == MemberState(LEFT)
