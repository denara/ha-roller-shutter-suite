"""Wish, constraint result, gate outcome and decision."""

import dataclasses
from datetime import UTC, datetime
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.model import (
    CONSTRAINT_REASONS,
    FULLY_CLOSED,
    FULLY_OPEN,
    GATE_RULE_REASONS,
    Constraint,
    ConstraintResult,
    Decision,
    Direction,
    GateKind,
    GateOutcome,
    GateRule,
    Layer,
    LayerReason,
    MemberTarget,
    Position,
    Wish,
    WishClass,
    WishKind,
)
from custom_components.roller_shutter_suite.core.reasons import (
    ReasonCategory,
    ReasonCode,
    codes_of,
)

LATER = datetime(2026, 3, 1, 18, 30, tzinfo=UTC)
NAIVE = datetime(2026, 3, 1, 18, 30)  # noqa: DTZ001 - the rejected case

LEFT = "cover.example_left"
RIGHT = "cover.example_right"
RAY_HEIGHT = 1.19


def _targets(left: int | None, right: int | None = None) -> tuple[MemberTarget, ...]:
    def position(value: int | None) -> Position | None:
        return None if value is None else Position(value)

    targets = [MemberTarget(LEFT, position(left))]
    if right is not None:
        targets.append(MemberTarget(RIGHT, position(right)))
    return tuple(targets)


# --- Enumerations follow the architecture document ---------------------------


def test_layers_are_listed_in_evaluation_order() -> None:
    """Section 2.1: fire first, schedule last."""
    assert [layer.value for layer in Layer] == [
        "fire",
        "protection",
        "sleep",
        "external_request",
        "privacy",
        "shading",
        "schedule",
    ]


def test_constraints_are_listed_in_order_of_application() -> None:
    """Section 2.2."""
    assert [constraint.value for constraint in Constraint] == [
        "direction",
        "sleep_room_exception",
        "lockout_protection",
        "ventilation_floor",
        "rain_while_ventilating",
        "frost_protection",
        "no_intermediate_position",
    ]


def test_gate_rules_are_listed_in_evaluation_order() -> None:
    """Section 2.3: maintenance lock first, dry-run last."""
    assert [rule.value for rule in GateRule] == [
        "maintenance_lock",
        "no_member_can_execute",
        "target_reached",
        "operating_mode",
        "pause",
        "person_at_window_dam",
        "manual_override_dam",
        "movement_in_flight",
        "motor_protection",
        "command_backoff",
        "staggering",
        "dry_run",
    ]


def test_wish_class_follows_from_the_layer() -> None:
    """Section 2.1: one fire layer, one protection layer, comfort below."""
    assert Layer.FIRE.wish_class is WishClass.FIRE
    assert Layer.PROTECTION.wish_class is WishClass.PROTECTION
    for layer in list(Layer)[2:]:
        assert layer.wish_class is WishClass.COMFORT
    assert [wish_class.value for wish_class in WishClass] == [
        "fire",
        "protection",
        "comfort",
    ]


# --- Member target ------------------------------------------------------------


def test_member_target_validation() -> None:
    """A target names its member; the position is a position or ``None``."""
    bad: Any = 50
    assert MemberTarget(LEFT, None).position is None
    with pytest.raises(ValueError, match="must not be empty"):
        MemberTarget("", Position(1))
    with pytest.raises(TypeError, match="Position"):
        MemberTarget(LEFT, bad)
    with pytest.raises(TypeError, match="str"):
        MemberTarget(bad, None)


# --- Wish ---------------------------------------------------------------------


def test_wish_with_target_position() -> None:
    """A target wish carries position, reason, layer, class and direction."""
    wish = Wish.target(
        Layer.SCHEDULE,
        ReasonCode.SCHEDULE_NIGHT,
        FULLY_CLOSED,
        direction=Direction.LOWER_ONLY,
    )

    assert wish.kind is WishKind.TARGET
    assert wish.position == FULLY_CLOSED
    assert wish.reason is ReasonCode.SCHEDULE_NIGHT
    assert wish.layer is Layer.SCHEDULE
    assert wish.wish_class is WishClass.COMFORT
    assert wish.direction is Direction.LOWER_ONLY
    assert wish.member_positions == ()


def test_wish_leave_alone_and_no_opinion() -> None:
    """The other two answers carry a reason but no position."""
    hold = Wish.leave_alone(Layer.FIRE, ReasonCode.FIRE_UNACKNOWLEDGED)
    aside = Wish.no_opinion(Layer.SLEEP, ReasonCode.INACTIVE)

    assert hold.kind is WishKind.LEAVE_ALONE
    assert hold.position is None
    assert hold.wish_class is WishClass.FIRE
    assert aside.kind is WishKind.NO_OPINION
    assert aside.reason is ReasonCode.INACTIVE


def test_wish_with_a_position_but_no_reason_is_rejected() -> None:
    """A reason code is mandatory, and it is a code, never free text."""
    target: Any = Wish.target
    with pytest.raises(TypeError):
        target(Layer.SCHEDULE, position=FULLY_OPEN)
    with pytest.raises(TypeError, match="reason of a wish"):
        target(Layer.SCHEDULE, None, FULLY_OPEN)
    with pytest.raises(TypeError, match="reason of a wish"):
        target(Layer.SCHEDULE, "because", FULLY_OPEN)
    with pytest.raises(TypeError, match="reason of a wish"):
        Wish.no_opinion(Layer.SCHEDULE, "inactive")  # type: ignore[arg-type]


def test_wish_kind_and_payload_have_to_fit() -> None:
    """A target needs a position; the other kinds must not carry one."""
    with pytest.raises(ValueError, match="needs either one position"):
        Wish(Layer.SLEEP, WishKind.TARGET, ReasonCode.SLEEP_MODE)
    for kind in (WishKind.LEAVE_ALONE, WishKind.NO_OPINION):
        for payload in (
            {"position": FULLY_OPEN},
            {"direction": Direction.RAISE_ONLY},
            {"member_positions": _targets(10)},
            {"ray_height": 1.2},
        ):
            with pytest.raises(ValueError, match="carries no position"):
                Wish(Layer.SLEEP, kind, ReasonCode.SLEEP_MODE, **payload)  # type: ignore[arg-type]


def test_wish_types_are_checked() -> None:
    """Layer, kind, position and direction are not free text either."""
    bad: Any = "x"
    with pytest.raises(TypeError, match="layer"):
        Wish.leave_alone(bad, ReasonCode.INACTIVE)
    with pytest.raises(TypeError, match="kind"):
        Wish(Layer.FIRE, bad, ReasonCode.INACTIVE)
    with pytest.raises(TypeError, match="position of a wish"):
        Wish.target(Layer.SLEEP, ReasonCode.SLEEP_MODE, bad)
    with pytest.raises(TypeError, match="direction"):
        Wish.target(Layer.SLEEP, ReasonCode.SLEEP_MODE, FULLY_OPEN, direction=bad)


def test_shading_wish_carries_ray_height_and_member_positions() -> None:
    """Decision 9: one decision (ray height), one position per member."""
    wish = Wish.target_per_member(
        Layer.SHADING,
        ReasonCode.SHADING_GEOMETRIC,
        [MemberTarget(LEFT, Position(21)), MemberTarget(RIGHT, Position(36))],
        ray_height=RAY_HEIGHT,
    )

    assert wish.kind is WishKind.TARGET
    assert wish.position is None
    assert wish.member_positions == _targets(21, 36)
    assert wish.ray_height == RAY_HEIGHT
    assert isinstance(wish.member_positions, tuple)


def test_member_positions_of_a_wish_are_validated() -> None:
    """One position for all or one per member, never both; members unique and set."""
    with pytest.raises(ValueError, match="needs either one position"):
        Wish(
            Layer.SHADING,
            WishKind.TARGET,
            ReasonCode.SHADING_GEOMETRIC,
            position=Position(21),
            member_positions=_targets(21, 36),
        )
    with pytest.raises(ValueError, match="needs either one position"):
        Wish.target_per_member(Layer.SHADING, ReasonCode.SHADING_GEOMETRIC, [])
    with pytest.raises(ValueError, match="occurs twice"):
        Wish.target_per_member(
            Layer.SHADING,
            ReasonCode.SHADING_GEOMETRIC,
            [MemberTarget(LEFT, Position(21)), MemberTarget(LEFT, Position(36))],
        )
    with pytest.raises(ValueError, match="position for every member"):
        Wish.target_per_member(
            Layer.SHADING,
            ReasonCode.SHADING_GEOMETRIC,
            [MemberTarget(LEFT, Position(21)), MemberTarget(RIGHT, None)],
        )
    with pytest.raises(ValueError, match="finite"):
        Wish.target(
            Layer.SHADING,
            ReasonCode.SHADING_GEOMETRIC,
            Position(21),
            ray_height=float("inf"),
        )
    with pytest.raises(TypeError, match="number"):
        Wish.target(
            Layer.SHADING,
            ReasonCode.SHADING_GEOMETRIC,
            Position(21),
            ray_height="high",  # type: ignore[arg-type]
        )


def test_wish_is_immutable_hashable_and_compares_by_value() -> None:
    """Wishes are values."""
    wish = Wish.target(Layer.SLEEP, ReasonCode.SLEEP_MODE, Position(10))
    same = Wish.target(Layer.SLEEP, ReasonCode.SLEEP_MODE, Position(10))

    assert wish == same
    assert hash(wish) == hash(same)
    assert wish != Wish.target(Layer.SLEEP, ReasonCode.SLEEP_MODE, Position(11))
    with pytest.raises(dataclasses.FrozenInstanceError):
        wish.position = Position(1)  # type: ignore[misc]


def test_layer_reason_is_validated() -> None:
    """Why a layer did not win is a layer and a code."""
    bad: Any = "sleep"
    assert LayerReason(Layer.SLEEP, ReasonCode.INACTIVE).reason is ReasonCode.INACTIVE
    with pytest.raises(TypeError, match="layer"):
        LayerReason(bad, ReasonCode.INACTIVE)
    with pytest.raises(TypeError, match="reason"):
        LayerReason(Layer.SLEEP, bad)


# --- Constraint result ----------------------------------------------------------


def test_constraint_result_lists_the_targets_after_it() -> None:
    """A result names constraint, reason and every member's target."""
    result = ConstraintResult(
        Constraint.VENTILATION_FLOOR, ReasonCode.VENTILATION_FLOOR, list(_targets(30))
    )

    assert result.targets == _targets(30)
    assert isinstance(result.targets, tuple)
    assert hash(result) == hash(
        ConstraintResult(
            Constraint.VENTILATION_FLOOR, ReasonCode.VENTILATION_FLOOR, _targets(30)
        )
    )


def test_constraint_result_can_pin_a_member() -> None:
    """A pinned member has no position: it stays where it is."""
    result = ConstraintResult(
        Constraint.LOCKOUT_PROTECTION, ReasonCode.LOCKOUT_DOOR_OPEN, _targets(None)
    )

    assert result.targets[0].position is None


def test_constraint_result_is_validated() -> None:
    """Types are checked, targets are present and unique."""
    bad: Any = "x"
    with pytest.raises(TypeError, match="constraint"):
        ConstraintResult(bad, ReasonCode.FROST_LIMIT, _targets(90))
    with pytest.raises(TypeError, match="reason"):
        ConstraintResult(Constraint.FROST_PROTECTION, bad, _targets(90))
    with pytest.raises(ValueError, match="every member"):
        ConstraintResult(Constraint.FROST_PROTECTION, ReasonCode.FROST_LIMIT, ())
    with pytest.raises(TypeError, match="MemberTarget"):
        ConstraintResult(Constraint.FROST_PROTECTION, ReasonCode.FROST_LIMIT, (bad,))
    with pytest.raises(ValueError, match="occurs twice"):
        ConstraintResult(
            Constraint.FROST_PROTECTION,
            ReasonCode.FROST_LIMIT,
            _targets(90) + _targets(90),
        )


# --- Gate outcome -----------------------------------------------------------------


def test_gate_send() -> None:
    """Send: no rule applied, the reason is ``sent``."""
    outcome = GateOutcome.send()

    assert outcome.kind is GateKind.SEND
    assert outcome.reason is ReasonCode.SENT
    assert outcome.rule is None
    assert outcome.until is None
    assert outcome.dry_run is False


def test_gate_defer_until_a_point_in_time() -> None:
    """Defer names the rule, the reason and the time."""
    outcome = GateOutcome.defer(
        GateRule.PERSON_AT_WINDOW_DAM, ReasonCode.PERSON_AT_WINDOW, LATER
    )

    assert outcome.kind is GateKind.DEFER
    assert outcome.until == LATER
    assert outcome.rule is GateRule.PERSON_AT_WINDOW_DAM


def test_gate_defer_until_a_condition_without_a_known_time() -> None:
    """Waiting for a member has no end time, but a latest re-evaluation."""
    outcome = GateOutcome.defer(
        GateRule.NO_MEMBER_CAN_EXECUTE,
        ReasonCode.COVER_UNAVAILABLE,
        reevaluate_no_later_than=LATER,
    )

    assert outcome.until is None
    assert outcome.reevaluate_no_later_than == LATER
    assert (
        GateOutcome.defer(
            GateRule.PERSON_AT_WINDOW_DAM, ReasonCode.PERSON_AT_WINDOW, LATER
        ).reevaluate_no_later_than
        is None
    )


def test_gate_deferral_needs_exactly_one_of_the_two_times() -> None:
    """Nothing waits forever: a deferral without any time is refused."""
    with pytest.raises(ValueError, match="either the time at which it ends"):
        GateOutcome.defer(GateRule.NO_MEMBER_CAN_EXECUTE, ReasonCode.COVER_UNAVAILABLE)
    with pytest.raises(ValueError, match="either the time at which it ends"):
        GateOutcome.defer(
            GateRule.STAGGERING,
            ReasonCode.STAGGERED,
            LATER,
            reevaluate_no_later_than=LATER,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        GateOutcome.defer(
            GateRule.NO_MEMBER_CAN_EXECUTE,
            ReasonCode.COVER_UNAVAILABLE,
            reevaluate_no_later_than=NAIVE,
        )
    with pytest.raises(ValueError, match="only a deferral"):
        GateOutcome(
            GateKind.SUPPRESS,
            ReasonCode.PAUSED,
            rule=GateRule.PAUSE,
            reevaluate_no_later_than=LATER,
        )


def test_gate_suppress() -> None:
    """Suppress names the rule and the reason."""
    outcome = GateOutcome.suppress(
        GateRule.MAINTENANCE_LOCK, ReasonCode.MAINTENANCE_LOCK
    )

    assert outcome.kind is GateKind.SUPPRESS
    assert outcome.rule is GateRule.MAINTENANCE_LOCK


def test_gate_accepts_the_capability_reason_for_rule_2() -> None:
    """Section 2.3, rule 2: "suppress with the capability reason"."""
    outcome = GateOutcome.suppress(
        GateRule.NO_MEMBER_CAN_EXECUTE, ReasonCode.CAPABILITY_MISSING
    )

    assert outcome.reason is ReasonCode.CAPABILITY_MISSING


def test_dry_run_window_would_have_sent() -> None:
    """The last rule records the would-be command."""
    outcome = GateOutcome.would_have_sent(_targets(100, 100))

    assert outcome.kind is GateKind.SUPPRESS
    assert outcome.reason is ReasonCode.DRY_RUN
    assert outcome.rule is GateRule.DRY_RUN
    assert outcome.dry_run is True
    assert outcome.would_send == _targets(100, 100)


def test_dry_run_window_would_have_been_held_back_by_an_earlier_rule() -> None:
    """The hypothetical outcome names the rule that would have held the wish."""
    paused = GateOutcome.suppress(GateRule.PAUSE, ReasonCode.PAUSED, dry_run=True)
    waiting = GateOutcome.defer(
        GateRule.MOTOR_PROTECTION, ReasonCode.MIN_INTERVAL, LATER, dry_run=True
    )

    assert paused.dry_run is True
    assert paused.rule is GateRule.PAUSE
    assert paused.would_send == ()
    assert waiting.dry_run is True
    assert waiting.until == LATER


def test_gate_rejects_a_naive_deferral() -> None:
    """Timestamps are timezone-aware at every boundary."""
    with pytest.raises(ValueError, match="timezone-aware"):
        GateOutcome.defer(GateRule.STAGGERING, ReasonCode.STAGGERED, NAIVE)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"kind": GateKind.SEND, "reason": ReasonCode.PAUSED}, "has the reason 'sent'"),
        (
            {
                "kind": GateKind.SEND,
                "reason": ReasonCode.SENT,
                "rule": GateRule.PAUSE,
            },
            "no gate rule applied",
        ),
        (
            {"kind": GateKind.SEND, "reason": ReasonCode.SENT, "until": LATER},
            "only a deferral",
        ),
        (
            {"kind": GateKind.SEND, "reason": ReasonCode.SENT, "dry_run": True},
            "never sends",
        ),
        (
            {
                "kind": GateKind.SEND,
                "reason": ReasonCode.SENT,
                "would_send": _targets(0),
            },
            "no would-be command",
        ),
        (
            {
                "kind": GateKind.SUPPRESS,
                "reason": ReasonCode.SENT,
                "rule": GateRule.PAUSE,
            },
            "only the outcome 'send'",
        ),
        ({"kind": GateKind.SUPPRESS, "reason": ReasonCode.PAUSED}, "names the rule"),
        (
            {
                "kind": GateKind.SUPPRESS,
                "reason": ReasonCode.PAUSED,
                "rule": GateRule.PAUSE,
                "until": LATER,
            },
            "only a deferral has an end",
        ),
        (
            {
                "kind": GateKind.SUPPRESS,
                "reason": ReasonCode.PAUSED,
                "rule": GateRule.DRY_RUN,
                "dry_run": True,
            },
            "'dry_run' does not give the reason 'paused'",
        ),
        (
            {
                "kind": GateKind.SUPPRESS,
                "reason": ReasonCode.DRY_RUN,
                "rule": GateRule.PAUSE,
                "dry_run": True,
            },
            "'pause' does not give the reason 'dry_run'",
        ),
        (
            {
                "kind": GateKind.SUPPRESS,
                "reason": ReasonCode.DRY_RUN,
                "rule": GateRule.DRY_RUN,
                "dry_run": True,
            },
            "records the would-be command",
        ),
        (
            {
                "kind": GateKind.SUPPRESS,
                "reason": ReasonCode.PAUSED,
                "rule": GateRule.PAUSE,
                "dry_run": True,
                "would_send": _targets(0),
            },
            "records the would-be command",
        ),
        (
            {
                "kind": GateKind.SUPPRESS,
                "reason": ReasonCode.DRY_RUN,
                "rule": GateRule.DRY_RUN,
                "dry_run": False,
                "would_send": _targets(0),
            },
            "for a window in dry-run",
        ),
        (
            {
                "kind": GateKind.DEFER,
                "reason": ReasonCode.DRY_RUN,
                "rule": GateRule.DRY_RUN,
                "until": LATER,
                "dry_run": True,
                "would_send": _targets(0),
            },
            "for a window in dry-run",
        ),
        (
            {
                "kind": GateKind.SUPPRESS,
                "reason": ReasonCode.DRY_RUN,
                "rule": GateRule.DRY_RUN,
                "dry_run": True,
                "would_send": _targets(None),
            },
            "position for every member",
        ),
    ],
)
def test_gate_outcome_that_contradicts_itself_is_rejected(
    arguments: dict[str, Any], message: str
) -> None:
    """Every inconsistent combination is refused on construction."""
    with pytest.raises(ValueError, match=message):
        GateOutcome(**arguments)


def test_gate_outcome_types_are_checked() -> None:
    """Kind, reason, rule and flag are typed values."""
    bad: Any = "x"
    with pytest.raises(TypeError, match="kind"):
        GateOutcome(bad, ReasonCode.SENT)
    with pytest.raises(TypeError, match="reason"):
        GateOutcome(GateKind.SEND, bad)
    with pytest.raises(TypeError, match="rule"):
        GateOutcome(GateKind.SUPPRESS, ReasonCode.PAUSED, rule=bad)
    with pytest.raises(TypeError, match="dry-run flag"):
        GateOutcome(GateKind.SEND, ReasonCode.SENT, dry_run=bad)
    with pytest.raises(TypeError, match="end of a deferral"):
        GateOutcome.defer(GateRule.STAGGERING, ReasonCode.STAGGERED, bad)


def test_gate_outcome_is_hashable_and_compares_by_value() -> None:
    """Gate outcomes are values."""
    assert GateOutcome.send() == GateOutcome.send()
    assert hash(GateOutcome.would_have_sent(_targets(0))) == hash(
        GateOutcome.would_have_sent(_targets(0))
    )
    assert GateOutcome.send() != GateOutcome.suppress(GateRule.PAUSE, ReasonCode.PAUSED)


# --- Decision -----------------------------------------------------------------------


def _night_wish() -> Wish:
    return Wish.target(
        Layer.SCHEDULE,
        ReasonCode.SCHEDULE_NIGHT,
        FULLY_CLOSED,
        direction=Direction.LOWER_ONLY,
    )


def test_decision_evening_closing_with_a_tilted_window() -> None:
    """Reference situation 11: schedule_night / ventilation_floor / sent."""
    decision = Decision(
        winning_wish=_night_wish(),
        other_layers=[
            LayerReason(Layer.FIRE, ReasonCode.INACTIVE),
            LayerReason(Layer.PROTECTION, ReasonCode.INACTIVE),
            LayerReason(Layer.SLEEP, ReasonCode.NOT_CONFIGURED),
            LayerReason(Layer.SHADING, ReasonCode.OUTSIDE_EPISODE),
        ],
        constraints=[
            ConstraintResult(
                Constraint.VENTILATION_FLOOR,
                ReasonCode.VENTILATION_FLOOR,
                _targets(30, 30),
            )
        ],
        targets=list(_targets(30, 30)),
        gate=GateOutcome.send(),
    )

    assert decision.target == Position(30)
    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.SCHEDULE_NIGHT
    assert [result.reason for result in decision.constraints] == [
        ReasonCode.VENTILATION_FLOOR
    ]
    assert decision.gate == GateOutcome.send()
    assert isinstance(decision.other_layers, tuple)
    assert isinstance(decision.constraints, tuple)
    assert isinstance(decision.targets, tuple)
    assert hash(decision) == hash(dataclasses.replace(decision))


def test_decision_with_different_member_targets_shows_no_window_target() -> None:
    """Per-member targets are the detail; there is no common target to show."""
    decision = Decision(
        winning_wish=Wish.target_per_member(
            Layer.SHADING,
            ReasonCode.SHADING_GEOMETRIC,
            _targets(21, 36),
            ray_height=RAY_HEIGHT,
        ),
        targets=_targets(21, 36),
        gate=GateOutcome.send(),
    )

    assert decision.target is None
    assert [target.position for target in decision.targets] == [
        Position(21),
        Position(36),
    ]


def test_decision_fire_in_dry_run_records_would_open() -> None:
    """Reference situation 2: fire_alarm / - / dry_run (would send 100)."""
    decision = Decision(
        winning_wish=Wish.target(Layer.FIRE, ReasonCode.FIRE_ALARM, FULLY_OPEN),
        targets=_targets(100),
        gate=GateOutcome.would_have_sent(_targets(100)),
    )

    assert decision.gate is not None
    assert decision.gate.would_send[0].position == FULLY_OPEN


def test_decision_leave_alone_has_no_target_and_no_gate() -> None:
    """Reference situation 3a: fire_unacknowledged / - / -."""
    decision = Decision(
        winning_wish=Wish.leave_alone(Layer.FIRE, ReasonCode.FIRE_UNACKNOWLEDGED)
    )

    assert decision.target is None
    assert decision.targets == ()
    assert decision.gate is None


def test_decision_pinned_by_a_constraint_does_not_reach_the_gate() -> None:
    """Reference situation 4: protection_event / lockout_door_open / -."""
    decision = Decision(
        winning_wish=Wish.target(
            Layer.PROTECTION, ReasonCode.PROTECTION_EVENT, FULLY_CLOSED
        ),
        constraints=[
            ConstraintResult(
                Constraint.LOCKOUT_PROTECTION,
                ReasonCode.LOCKOUT_DOOR_OPEN,
                _targets(None),
            )
        ],
        targets=_targets(None),
    )

    assert decision.target is None
    assert decision.gate is None


def test_decision_without_any_opinion() -> None:
    """A window without a configured schedule can end without a winner."""
    decision = Decision(
        winning_wish=None,
        other_layers=[LayerReason(Layer.SCHEDULE, ReasonCode.NOT_CONFIGURED)],
    )

    assert decision.winning_wish is None
    assert decision.target is None


def test_decision_with_one_pinned_and_one_moving_member() -> None:
    """Only the members that still have a target are sent."""
    decision = Decision(
        winning_wish=Wish.target(
            Layer.SCHEDULE,
            ReasonCode.SCHEDULE_DAY,
            Position(60),
            direction=Direction.RAISE_ONLY,
        ),
        constraints=[
            ConstraintResult(
                Constraint.DIRECTION, ReasonCode.ONLY_RAISE, _targets(None, 60)
            )
        ],
        targets=_targets(None, 60),
        gate=GateOutcome.would_have_sent([MemberTarget(RIGHT, Position(60))]),
    )

    assert decision.target is None
    assert decision.gate is not None


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            {"winning_wish": Wish.no_opinion(Layer.SLEEP, ReasonCode.INACTIVE)},
            "cannot win",
        ),
        (
            {
                "winning_wish": Wish.leave_alone(
                    Layer.FIRE, ReasonCode.FIRE_UNACKNOWLEDGED
                ),
                "other_layers": [LayerReason(Layer.FIRE, ReasonCode.INACTIVE)],
            },
            "not one of the other layers",
        ),
        (
            {
                "winning_wish": None,
                "other_layers": [
                    LayerReason(Layer.SLEEP, ReasonCode.INACTIVE),
                    LayerReason(Layer.SLEEP, ReasonCode.NOT_CONFIGURED),
                ],
            },
            "listed twice",
        ),
        (
            {"winning_wish": _night_wish()},
            "if, and only if",
        ),
        (
            {
                "winning_wish": Wish.leave_alone(
                    Layer.FIRE, ReasonCode.FIRE_UNACKNOWLEDGED
                ),
                "targets": _targets(100),
                "gate": GateOutcome.send(),
            },
            "if, and only if",
        ),
        (
            {
                "winning_wish": None,
                "constraints": [
                    ConstraintResult(
                        Constraint.FROST_PROTECTION,
                        ReasonCode.FROST_LIMIT,
                        _targets(90),
                    )
                ],
            },
            "apply to a target only",
        ),
        (
            {"winning_wish": _night_wish(), "targets": _targets(0)},
            "reaches the gate",
        ),
        (
            {
                "winning_wish": _night_wish(),
                "targets": _targets(None),
                "gate": GateOutcome.send(),
            },
            "nothing reaches the gate",
        ),
        (
            {
                "winning_wish": _night_wish(),
                "targets": _targets(0),
                "gate": GateOutcome.would_have_sent(_targets(10)),
            },
            "consists of the decision's targets",
        ),
        (
            {
                "winning_wish": _night_wish(),
                "targets": _targets(0) + _targets(0),
                "gate": GateOutcome.send(),
            },
            "occurs twice",
        ),
    ],
)
def test_decision_whose_parts_contradict_each_other_is_rejected(
    arguments: dict[str, Any], message: str
) -> None:
    """A decision record is consistent or it does not exist."""
    with pytest.raises(ValueError, match=message):
        Decision(**arguments)


def test_decision_types_are_checked() -> None:
    """No free text anywhere in a decision."""
    bad: Any = "x"
    with pytest.raises(TypeError, match="winning wish"):
        Decision(winning_wish=bad)
    with pytest.raises(TypeError, match="layer reason"):
        Decision(winning_wish=None, other_layers=[bad])
    with pytest.raises(TypeError, match="constraint of a decision"):
        Decision(winning_wish=_night_wish(), constraints=[bad], targets=_targets(0))
    with pytest.raises(TypeError, match="targets of a decision"):
        Decision(winning_wish=_night_wish(), targets=[bad])
    with pytest.raises(TypeError, match="gate outcome"):
        Decision(winning_wish=_night_wish(), targets=_targets(0), gate=bad)


# --- The return to the manual position (decision 14) -----------------------------------


def test_return_to_the_manual_position_is_a_comfort_wish_of_the_protection_layer() -> (
    None
):
    """The class follows from the layer, except for this one reason code."""
    back = Wish.target(
        Layer.PROTECTION, ReasonCode.PROTECTION_RETURN_MANUAL, Position(55)
    )
    event = Wish.target(Layer.PROTECTION, ReasonCode.PROTECTION_EVENT, FULLY_CLOSED)

    assert back.layer is Layer.PROTECTION
    assert back.wish_class is WishClass.COMFORT
    assert event.wish_class is WishClass.PROTECTION
    assert Layer.PROTECTION.wish_class is WishClass.PROTECTION


@pytest.mark.parametrize(
    "layer", [layer for layer in Layer if layer is not Layer.PROTECTION]
)
def test_return_to_the_manual_position_comes_from_the_protection_layer_only(
    layer: Layer,
) -> None:
    """No other layer can carry the reason, whatever the kind of wish."""
    reason = ReasonCode.PROTECTION_RETURN_MANUAL
    with pytest.raises(ValueError, match="belongs to a wish of the protection layer"):
        Wish.target(layer, reason, Position(55))
    with pytest.raises(ValueError, match="belongs to a wish of the protection layer"):
        Wish.leave_alone(layer, reason)
    with pytest.raises(ValueError, match="belongs to a wish of the protection layer"):
        Wish.no_opinion(layer, reason)


@pytest.mark.parametrize(
    "reason",
    [
        code
        for code in codes_of(ReasonCategory.LAYER)
        if code is not ReasonCode.PROTECTION_RETURN_MANUAL
    ],
)
def test_every_other_wish_has_the_class_of_its_layer(reason: ReasonCode) -> None:
    """The exception is exactly one reason code."""
    for layer in Layer:
        assert Wish.target(layer, reason, FULLY_OPEN).wish_class is layer.wish_class


# --- The displayed target -------------------------------------------------------------


def test_decision_shows_the_common_target_of_its_members() -> None:
    """The same target for all members is the target of the window."""
    decision = Decision(
        winning_wish=Wish.target(Layer.SLEEP, ReasonCode.SLEEP_MODE, Position(10)),
        targets=_targets(10, 10),
        gate=GateOutcome.send(),
    )

    assert decision.target == Position(10)


def test_decision_with_a_pinned_member_shows_no_window_target() -> None:
    """One member stays, the other moves: no common target, whoever is first."""
    moving_first = (MemberTarget(LEFT, Position(60)), MemberTarget(RIGHT, None))
    for targets in (_targets(None, 60), moving_first):
        decision = Decision(
            winning_wish=Wish.target(
                Layer.SCHEDULE,
                ReasonCode.SCHEDULE_DAY,
                Position(60),
                direction=Direction.RAISE_ONLY,
            ),
            constraints=[
                ConstraintResult(Constraint.DIRECTION, ReasonCode.ONLY_RAISE, targets)
            ],
            targets=targets,
            gate=GateOutcome.send(),
        )

        assert decision.target is None


# --- Reason codes are tied to their group -------------------------------------------------


def _codes_outside(*categories: ReasonCategory) -> list[ReasonCode]:
    return [code for code in ReasonCode if code.category not in categories]


@pytest.mark.parametrize("reason", _codes_outside(ReasonCategory.LAYER))
def test_wish_for_a_target_takes_only_codes_of_winning_layers(
    reason: ReasonCode,
) -> None:
    """``command_failed``, ``paused`` or ``inactive`` are not reasons for a target."""
    with pytest.raises(ValueError, match="must be a code of the group 'layer'"):
        Wish.target(Layer.SCHEDULE, reason, FULLY_OPEN)


@pytest.mark.parametrize(
    "reason", _codes_outside(ReasonCategory.LAYER, ReasonCategory.LAYER_INACTIVE)
)
def test_other_wishes_and_layer_reasons_take_only_layer_codes(
    reason: ReasonCode,
) -> None:
    """No constraint, gate or event-only code explains what a layer did."""
    with pytest.raises(ValueError, match="must be a code of the group"):
        Wish.no_opinion(Layer.SLEEP, reason)
    with pytest.raises(ValueError, match="must be a code of the group"):
        Wish.leave_alone(Layer.FIRE, reason)
    with pytest.raises(ValueError, match="must be a code of the group"):
        LayerReason(Layer.SLEEP, reason)


@pytest.mark.parametrize(
    "reason", codes_of(ReasonCategory.LAYER) + codes_of(ReasonCategory.LAYER_INACTIVE)
)
def test_every_layer_code_explains_a_layer(reason: ReasonCode) -> None:
    """A safety layer holds the window with ``input_unavailable``, for example."""
    assert Wish.leave_alone(Layer.PROTECTION, reason).reason is reason
    assert Wish.no_opinion(Layer.PROTECTION, reason).reason is reason
    assert LayerReason(Layer.PROTECTION, reason).reason is reason


@pytest.mark.parametrize("reason", _codes_outside(ReasonCategory.CONSTRAINT))
def test_constraint_result_takes_only_constraint_codes(reason: ReasonCode) -> None:
    """The group "constraints" and nothing else."""
    with pytest.raises(ValueError, match="must be a code of the group 'constraint'"):
        ConstraintResult(Constraint.FROST_PROTECTION, reason, _targets(90))


def test_every_constraint_code_belongs_to_exactly_one_constraint() -> None:
    """Sections 2.2 and 5: the pairing of constraint and reason is fixed."""
    paired = [code for codes in CONSTRAINT_REASONS.values() for code in codes]

    assert set(CONSTRAINT_REASONS) == set(Constraint)
    assert sorted(paired) == sorted(codes_of(ReasonCategory.CONSTRAINT))
    for constraint, codes in CONSTRAINT_REASONS.items():
        for code in codes:
            assert ConstraintResult(constraint, code, _targets(50)).reason is code
    with pytest.raises(ValueError, match="does not report the reason 'frost_limit'"):
        ConstraintResult(
            Constraint.VENTILATION_FLOOR, ReasonCode.FROST_LIMIT, _targets(90)
        )


@pytest.mark.parametrize(
    "reason",
    [
        code
        for code in _codes_outside(ReasonCategory.GATE)
        if code is not ReasonCode.CAPABILITY_MISSING
    ],
)
def test_gate_outcome_takes_only_gate_codes_and_the_capability_reason(
    reason: ReasonCode,
) -> None:
    """``fire_alarm`` or ``command_failed`` never explain a gate outcome."""
    with pytest.raises(ValueError, match="must be a code of the group 'gate'"):
        GateOutcome.suppress(GateRule.PAUSE, reason)


def test_every_gate_code_belongs_to_exactly_one_rule() -> None:
    """Sections 2.3 and 5: the pairing of rule and reason is fixed."""
    paired = [code for codes in GATE_RULE_REASONS.values() for code in codes]
    expected = [
        code for code in codes_of(ReasonCategory.GATE) if code is not ReasonCode.SENT
    ] + [ReasonCode.CAPABILITY_MISSING]

    assert set(GATE_RULE_REASONS) == set(GateRule)
    assert sorted(paired) == sorted(expected)
    for rule, codes in GATE_RULE_REASONS.items():
        if rule is GateRule.DRY_RUN:
            continue
        for code in codes:
            assert GateOutcome.suppress(rule, code).reason is code


def test_gate_rule_and_reason_have_to_fit() -> None:
    """The rule ``pause`` cannot carry the reason ``maintenance_lock``."""
    with pytest.raises(
        ValueError, match="'pause' does not give the reason 'maintenance_lock'"
    ):
        GateOutcome.suppress(GateRule.PAUSE, ReasonCode.MAINTENANCE_LOCK)
    with pytest.raises(ValueError, match="does not give the reason"):
        GateOutcome.suppress(GateRule.PAUSE, ReasonCode.CAPABILITY_MISSING)


# --- The same members everywhere in a decision -------------------------------------------------


def _other(position: int) -> tuple[MemberTarget, ...]:
    return (MemberTarget("cover.example_other", Position(position)),)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (
            {
                "winning_wish": Wish.target(
                    Layer.SLEEP, ReasonCode.SLEEP_MODE, Position(30)
                ),
                "constraints": [
                    ConstraintResult(
                        Constraint.VENTILATION_FLOOR,
                        ReasonCode.VENTILATION_FLOOR,
                        _other(30),
                    )
                ],
                "targets": _targets(30),
                "gate": GateOutcome.send(),
            },
            "every constraint result names the same members",
        ),
        (
            {
                "winning_wish": Wish.target(
                    Layer.SLEEP, ReasonCode.SLEEP_MODE, Position(30)
                ),
                "constraints": [
                    ConstraintResult(
                        Constraint.VENTILATION_FLOOR,
                        ReasonCode.VENTILATION_FLOOR,
                        tuple(reversed(_targets(30, 30))),
                    )
                ],
                "targets": _targets(30, 30),
                "gate": GateOutcome.send(),
            },
            "in the same order",
        ),
        (
            {
                "winning_wish": Wish.target_per_member(
                    Layer.SHADING, ReasonCode.SHADING_FIXED, _targets(30, 30)
                ),
                "targets": _targets(30),
                "gate": GateOutcome.send(),
            },
            "the member positions of the winning wish name the same members",
        ),
    ],
)
def test_decision_names_the_same_members_everywhere(
    arguments: dict[str, Any], message: str
) -> None:
    """Wish, constraint results and targets speak about one set of members."""
    with pytest.raises(ValueError, match=message):
        Decision(**arguments)
