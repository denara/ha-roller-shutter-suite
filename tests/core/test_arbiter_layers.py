"""Layers: fixed order, first opinion wins, every other layer reports why."""

import ast
import dataclasses
from pathlib import Path

import pytest

from custom_components.roller_shutter_suite.core.arbiter import (
    LayerRegistration,
    wish_for_missing_input,
)
from custom_components.roller_shutter_suite.core.engine import build_arbiter
from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    GateKind,
    Layer,
    LayerReason,
    MemberTarget,
    Position,
    SourceValue,
    WindowState,
    Wish,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import (
    LEFT,
    RIGHT,
    STUB_LAYERS,
    day,
    engine,
    fire,
    night,
    observed,
    snapshot,
    storm,
    window,
)

CORE = Path(__file__).parents[2] / "custom_components" / "roller_shutter_suite" / "core"


def _answers(wish: Wish) -> LayerRegistration:
    return LayerRegistration(wish.layer, lambda _config, _world: wish)


def test_the_first_layer_with_an_opinion_wins() -> None:
    """The schedule is the bottom layer; a storm above it wins."""
    calm = engine().recompute(snapshot(sources=day()))
    stormy = engine().recompute(snapshot(sources=storm()))

    assert calm.winning_wish is not None
    assert calm.winning_wish.layer is Layer.SCHEDULE
    assert calm.target == FULLY_OPEN
    assert stormy.winning_wish is not None
    assert stormy.winning_wish.layer is Layer.PROTECTION
    assert stormy.target == FULLY_CLOSED


def test_layers_are_asked_in_the_specified_order_whatever_the_registration_order() -> (
    None
):
    """Fire stands above protection although it was registered last."""
    decision = engine().recompute(snapshot(sources=fire(storm=SourceValue.of(True))))

    assert [registration.layer for registration in engine().arbiter.layers] == [
        Layer.FIRE,
        Layer.PROTECTION,
        Layer.SLEEP,
        Layer.SHADING,
        Layer.SCHEDULE,
    ]
    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.FIRE_ALARM
    assert decision.target == FULLY_OPEN


def test_every_layer_that_did_not_win_reports_why() -> None:
    """Above the winner: why it stepped aside. Below: what it would have wanted."""
    decision = engine().recompute(snapshot(sources=storm(sleep=SourceValue.of(True))))

    assert decision.other_layers == (
        LayerReason(Layer.FIRE, ReasonCode.INACTIVE),
        LayerReason(Layer.SLEEP, ReasonCode.SLEEP_MODE),
        LayerReason(Layer.EXTERNAL_REQUEST, ReasonCode.NOT_CONFIGURED),
        LayerReason(Layer.PRIVACY, ReasonCode.NOT_CONFIGURED),
        LayerReason(Layer.SHADING, ReasonCode.OUTSIDE_EPISODE),
        LayerReason(Layer.SCHEDULE, ReasonCode.SCHEDULE_DAY),
    )


def test_leave_alone_from_a_higher_layer_stops_the_lower_layers() -> None:
    """The fire alarm has ended and nobody acknowledged it: nothing moves."""
    decision = engine().recompute(
        snapshot(
            sources=storm(sleep=SourceValue.of(True)),
            state=WindowState(fire_unacknowledged=True),
        )
    )

    assert decision.winning_wish == Wish.leave_alone(
        Layer.FIRE, ReasonCode.FIRE_UNACKNOWLEDGED
    )
    assert decision.targets == ()
    assert decision.target is None
    assert decision.gate is None
    assert LayerReason(Layer.PROTECTION, ReasonCode.PROTECTION_EVENT) in (
        decision.other_layers
    )


def test_the_fire_layer_opens_while_the_alarm_is_active() -> None:
    """Also when an earlier alarm was never acknowledged."""
    decision = engine().recompute(
        snapshot(sources=fire(), state=WindowState(fire_unacknowledged=True))
    )

    assert decision.winning_wish == Wish.target(
        Layer.FIRE, ReasonCode.FIRE_ALARM, FULLY_OPEN
    )
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND


def test_after_the_acknowledgement_the_lower_layers_act_again() -> None:
    """The persisted flag is gone: the recompute falls through."""
    decision = engine().recompute(snapshot(sources=night()))

    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.SCHEDULE_NIGHT


def test_no_layer_with_an_opinion_means_no_winner_and_no_movement() -> None:
    """A window without a configured schedule."""
    decision = build_arbiter(()).recompute(window(), snapshot())

    assert decision.winning_wish is None
    assert decision.gate is None
    assert {entry.reason for entry in decision.other_layers} == {
        ReasonCode.NOT_CONFIGURED
    }
    assert len(decision.other_layers) == len(Layer)


# --- Missing input ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (SourceValue[bool].unavailable(), ReasonCode.INPUT_UNAVAILABLE),
        (SourceValue[bool].unknown(), ReasonCode.INPUT_UNKNOWN),
        (None, ReasonCode.INPUT_UNAVAILABLE),
    ],
)
def test_a_missing_input_never_becomes_a_position(
    value: SourceValue[bool] | None, reason: ReasonCode
) -> None:
    """A layer holds or steps aside; neither answer carries a position."""
    held = wish_for_missing_input(Layer.PROTECTION, value, hold=True)
    aside = wish_for_missing_input(Layer.SCHEDULE, value, hold=False)

    assert held == Wish.leave_alone(Layer.PROTECTION, reason)
    assert aside == Wish.no_opinion(Layer.SCHEDULE, reason)
    assert wish_for_missing_input(Layer.FIRE, SourceValue.of(False), hold=True) is None


def test_a_safety_layer_with_an_unavailable_input_holds_the_window() -> None:
    """The stub protection layer cannot see its trigger: nothing moves."""
    decision = engine().recompute(
        snapshot(sources=night(storm=SourceValue[bool].unavailable()))
    )

    assert decision.winning_wish == Wish.leave_alone(
        Layer.PROTECTION, ReasonCode.INPUT_UNAVAILABLE
    )
    assert decision.targets == ()
    assert decision.gate is None


def test_a_comfort_layer_with_an_unavailable_input_steps_aside() -> None:
    """The stub shading layer passes to the schedule and says why."""
    decision = engine().recompute(
        snapshot(sources=night(shading_position=SourceValue[int].unknown()))
    )

    assert decision.winning_wish is not None
    assert decision.winning_wish.layer is Layer.SCHEDULE
    assert LayerReason(Layer.SHADING, ReasonCode.INPUT_UNKNOWN) in decision.other_layers


# --- Members ----------------------------------------------------------------------


def test_one_position_applies_to_every_member() -> None:
    """The targets list every member of the window in its order."""
    decision = engine(window(LEFT, RIGHT)).recompute(
        snapshot(sources=night(), observation=observed(left=100, right=80))
    )

    assert decision.targets == (
        MemberTarget(LEFT, FULLY_CLOSED),
        MemberTarget(RIGHT, FULLY_CLOSED),
    )
    assert decision.target == FULLY_CLOSED


def test_a_wish_per_member_keeps_its_positions() -> None:
    """Shading with unequal members: no common target, the detail per member."""
    per_member = (MemberTarget(LEFT, Position(21)), MemberTarget(RIGHT, Position(36)))
    wish = Wish.target_per_member(
        Layer.SHADING, ReasonCode.SHADING_GEOMETRIC, per_member, ray_height=1.19
    )
    arbiter = build_arbiter([_answers(wish)])

    decision = arbiter.recompute(
        window(LEFT, RIGHT), snapshot(observation=observed(left=100, right=100))
    )

    assert decision.targets == per_member
    assert decision.target is None
    with pytest.raises(ValueError, match="names the members of the window"):
        arbiter.recompute(
            window(RIGHT, LEFT), snapshot(observation=observed(right=100, left=100))
        )


def test_the_snapshot_has_to_observe_the_members_of_the_window() -> None:
    """Another window's observation is refused instead of guessed at."""
    with pytest.raises(ValueError, match="observes other members"):
        engine(window(LEFT, RIGHT)).recompute(snapshot(sources=day()))


# --- Registration -----------------------------------------------------------------


def test_adding_a_layer_is_a_registration() -> None:
    """A new layer takes its place without any change to the arbiter."""
    privacy = _answers(
        Wish.target(Layer.PRIVACY, ReasonCode.PRIVACY_LIGHTS_ON, Position(20))
    )
    arbiter = build_arbiter([*STUB_LAYERS, privacy])

    decision = arbiter.recompute(window(), snapshot(sources=day()))

    assert decision.winning_wish is not None
    assert decision.winning_wish.layer is Layer.PRIVACY
    assert decision.target == Position(20)


def test_a_layer_is_registered_once_and_answers_for_itself() -> None:
    """Two functions for one layer, or an answer in another layer's name, are refused."""
    inactive = _answers(Wish.no_opinion(Layer.SLEEP, ReasonCode.INACTIVE))
    impostor = LayerRegistration(
        Layer.FIRE,
        lambda _config, _world: Wish.no_opinion(Layer.SLEEP, ReasonCode.INACTIVE),
    )
    bad: Layer = "fire"  # type: ignore[assignment]

    with pytest.raises(ValueError, match="'sleep' is registered twice"):
        build_arbiter([inactive, inactive])
    with pytest.raises(ValueError, match="answered with a wish of the layer 'sleep'"):
        build_arbiter([impostor]).recompute(window(), snapshot())
    with pytest.raises(TypeError, match="member of 'Layer'"):
        LayerRegistration(bad, inactive.evaluate)


# --- No state, no clock -----------------------------------------------------------


def test_the_same_inputs_always_give_the_same_decision() -> None:
    """Also from two arbiters that were built independently."""
    world = snapshot(sources=storm())

    decisions = [engine().recompute(world) for _ in range(5)]
    decisions += [engine().recompute(snapshot(sources=storm()))]

    assert all(decision == decisions[0] for decision in decisions)


def test_the_arbiter_keeps_nothing() -> None:
    """It is immutable, and a recompute leaves it and the snapshot as they were."""
    subject = engine()
    before = (
        subject.arbiter.layers,
        subject.arbiter.constraints,
        subject.arbiter.gate_rules,
    )
    world = snapshot(sources=storm())

    subject.recompute(world)

    assert world == snapshot(sources=storm())
    assert (
        subject.arbiter.layers,
        subject.arbiter.constraints,
        subject.arbiter.gate_rules,
    ) == before
    with pytest.raises(dataclasses.FrozenInstanceError):
        subject.arbiter.layers = ()  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        subject.config = window()  # type: ignore[misc]


def test_no_module_of_the_arbiter_reads_a_clock() -> None:
    """Time reaches the core through the snapshot only."""
    files = [
        *sorted((CORE / "arbiter").glob("*.py")),
        *sorted((CORE / "constraints").glob("*.py")),
        CORE / "engine.py",
    ]
    assert len(files) > 8  # noqa: PLR2004 - the modules of this block

    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name != "time" for alias in node.names), path.name
            if isinstance(node, ast.ImportFrom):
                assert node.module != "time", path.name
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"now", "utcnow", "today"}, path.name
