"""The decision record in plain data: the reason, the attributes, the event outcome.

These tests build decisions by hand, so every shape the core can produce is
shown, also those the arbiter of today does not produce yet (a layer that
holds the window where it is, members with different targets).
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import Enum

from custom_components.roller_shutter_suite.core.model import (
    Constraint,
    ConstraintResult,
    Decision,
    GateOutcome,
    GateRule,
    Layer,
    LayerReason,
    MemberTarget,
    Position,
    Wish,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from custom_components.roller_shutter_suite.record import (
    UNCHANGED,
    ReasonOutcome,
    active_reason,
    common_position,
    decision_attributes,
    member_targets,
    plain,
    reason_outcome,
)

LEFT = "cover.example_left"
RIGHT = "cover.example_right"
AT = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)


def _targets(*positions: int | None) -> tuple[MemberTarget, ...]:
    members = (LEFT, RIGHT)
    return tuple(
        MemberTarget(member, None if position is None else Position(position))
        for member, position in zip(members, positions, strict=False)
    )


def _night(gate: GateOutcome, *positions: int | None) -> Decision:
    """Return an evening decision for one member, or one per given position."""
    targets = _targets(*(positions or (0,)))
    wish = Wish.target_per_member(
        Layer.SCHEDULE,
        ReasonCode.SCHEDULE_NIGHT,
        tuple(MemberTarget(target.member_id, Position(0)) for target in targets),
    )
    return Decision(winning_wish=wish, targets=targets, gate=gate)


def test_nothing_wanted_names_the_lowest_layer_or_not_configured() -> None:
    """Without a winner, the bottom layer explains; without any layer, nothing is set up."""
    assert active_reason(Decision(winning_wish=None)) is ReasonCode.NOT_CONFIGURED
    decision = Decision(
        winning_wish=None,
        other_layers=(
            LayerReason(Layer.FIRE, ReasonCode.NOT_CONFIGURED),
            LayerReason(Layer.SCHEDULE, ReasonCode.FUNCTION_DISABLED_BY_FAULT),
        ),
    )
    assert active_reason(decision) is ReasonCode.FUNCTION_DISABLED_BY_FAULT
    assert reason_outcome(decision, sent=False, dry_run=False) is None
    attributes = decision_attributes(decision, dry_run=False)
    assert attributes["layer"] is None
    assert attributes["target"] is None
    assert attributes["gate_outcome"] is None


def test_a_layer_that_holds_the_window_is_the_reason_and_fires_nothing() -> None:
    """Fire over, not acknowledged: the window is left alone, no movement is wanted."""
    decision = Decision(
        winning_wish=Wish.leave_alone(Layer.FIRE, ReasonCode.FIRE_UNACKNOWLEDGED)
    )
    assert active_reason(decision) is ReasonCode.FIRE_UNACKNOWLEDGED
    assert reason_outcome(decision, sent=False, dry_run=False) is None
    assert decision_attributes(decision, dry_run=False)["wish"] == "leave_alone"


def test_the_outcome_of_the_gate() -> None:
    """Sent only if commands were given; a duplicate changes nothing; reached ends it."""
    send = _night(GateOutcome.send())
    outcome = reason_outcome(send, sent=True, dry_run=False)
    assert isinstance(outcome, ReasonOutcome)
    assert outcome.reason is ReasonCode.SENT
    assert reason_outcome(send, sent=False, dry_run=False) is None
    duplicate = _night(
        GateOutcome.suppress(GateRule.MOVEMENT_IN_FLIGHT, ReasonCode.DUPLICATE_COMMAND)
    )
    assert reason_outcome(duplicate, sent=False, dry_run=False) is UNCHANGED
    reached = _night(
        GateOutcome.suppress(GateRule.TARGET_REACHED, ReasonCode.TARGET_REACHED)
    )
    assert reason_outcome(reached, sent=False, dry_run=False) is None
    assert active_reason(reached) is ReasonCode.SCHEDULE_NIGHT
    deferred = _night(
        GateOutcome.defer(GateRule.MOTOR_PROTECTION, ReasonCode.MIN_INTERVAL, AT)
    )
    held = reason_outcome(deferred, sent=False, dry_run=False)
    assert isinstance(held, ReasonOutcome)
    assert held.as_event_data()["until"] == AT.isoformat()
    assert (
        decision_attributes(deferred, dry_run=False)["deferred_until"] == AT.isoformat()
    )


def test_members_with_different_targets_have_no_common_target() -> None:
    """The window shows no target; the diagnostics show every member."""
    decision = _night(GateOutcome.send(), 0, 30)
    assert decision_attributes(decision, dry_run=False)["target"] is None
    assert member_targets(decision.targets) == [
        {"member_id": LEFT, "position": 0},
        {"member_id": RIGHT, "position": 30},
    ]
    assert common_position(_targets(None, None)) is None


def test_a_constraint_that_pins_every_member_is_the_reason_of_the_event() -> None:
    """A closing held back by an open door: nothing reaches the gate."""
    pinned = _targets(None)
    decision = Decision(
        winning_wish=Wish.target(
            Layer.SCHEDULE, ReasonCode.SCHEDULE_NIGHT, Position(0)
        ),
        constraints=(
            ConstraintResult(Constraint.DIRECTION, ReasonCode.ONLY_LOWER, _targets(0)),
            ConstraintResult(
                Constraint.LOCKOUT_PROTECTION, ReasonCode.LOCKOUT_DOOR_OPEN, pinned
            ),
        ),
        targets=pinned,
    )
    outcome = reason_outcome(decision, sent=False, dry_run=False)
    assert isinstance(outcome, ReasonOutcome)
    assert outcome.reason is ReasonCode.LOCKOUT_DOOR_OPEN
    assert outcome.gate is None
    assert outcome.until is None
    assert active_reason(decision) is ReasonCode.LOCKOUT_DOOR_OPEN


class _Kind(Enum):
    ONE = 1


@dataclass(frozen=True)
class _Pair:
    left: object
    right: object


def test_plain_turns_settings_and_profiles_into_json_data() -> None:
    """Enumerations, times, durations, positions, collections, records; the rest by type."""
    assert plain(_Kind.ONE) == 1
    assert plain(Position(40)) == 40  # noqa: PLR2004
    assert plain(time(7, 30)) == "07:30:00"
    assert plain(timedelta(minutes=10)) == 600.0  # noqa: PLR2004
    assert plain({"a": (1, 2)}) == {"a": [1, 2]}
    assert plain(frozenset({"b", "a"})) == ["a", "b"]
    assert plain(_Pair(1, None)) == {"left": 1, "right": None}
    assert plain(object()) == "<object>"
