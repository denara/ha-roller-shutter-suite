"""Dry-run: the last gate rule, the simulated commands, and a record that is stable."""

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.arbiter import (
    arm,
    is_standing,
    remember_would_be_send,
    simulated_state,
)
from custom_components.roller_shutter_suite.core.engine import Engine
from custom_components.roller_shutter_suite.core.model import (
    ControlLevel,
    Controls,
    Decision,
    GateKind,
    GateOutcome,
    GateRule,
    ManualOverrideDam,
    MemberState,
    MemberTarget,
    MotorProtectionSettings,
    OperatingMode,
    OverrideEndRule,
    OwnCommand,
    PersonAtWindowDam,
    Position,
    PositionOwner,
    SimulatedState,
    SourceValue,
    TravelDirection,
    WindowState,
    WishClass,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import (
    DRY_RUN,
    LEFT,
    NOW,
    RIGHT,
    day,
    engine,
    fire,
    night,
    observed,
    snapshot,
    storm,
    window,
)

LATER = NOW + timedelta(minutes=15)


def _gate(decision: Decision) -> GateOutcome:
    assert decision.gate is not None
    return decision.gate


def _would_send(position: int, *members: str) -> GateOutcome:
    return GateOutcome.would_have_sent(
        MemberTarget(member, Position(position)) for member in (members or (LEFT,))
    )


def _run(
    subject: Engine,
    world: WorldSnapshot,
    times: int = 1,
    step: timedelta = timedelta(0),
) -> tuple[list[Decision], WindowState]:
    """Recompute repeatedly, feeding the state of each decision into the next."""
    decisions: list[Decision] = []
    for _ in range(times):
        decision = subject.recompute(world)
        decisions.append(decision)
        world = replace(
            world, time=world.time + step, state=subject.state_after(world, decision)
        )
    return decisions, world.state


# --- Dry-run is the last rule -------------------------------------------------------


@pytest.mark.parametrize(
    ("sources", "target"), [(fire(), 100), (storm(), 0), (night(), 0)]
)
def test_in_dry_run_nothing_is_sent_and_the_record_shows_the_would_be_command(
    sources: dict[str, Any], target: int
) -> None:
    """Also for fire."""
    gate = _gate(engine().recompute(snapshot(sources=sources, controls=DRY_RUN)))

    assert gate == _would_send(target)
    assert gate.kind is GateKind.SUPPRESS
    assert gate.reason is ReasonCode.DRY_RUN
    assert gate.rule is GateRule.DRY_RUN
    assert gate.dry_run is True


@pytest.mark.parametrize(
    ("controls", "state", "sources", "reason"),
    [
        pytest.param(
            Controls(dry_run=True, group_level=ControlLevel(paused=True)),
            WindowState(),
            night(),
            ReasonCode.PAUSED,
            id="pause",
        ),
        pytest.param(
            Controls(dry_run=True, window_level=ControlLevel(mode=OperatingMode.OFF)),
            WindowState(),
            storm(),
            ReasonCode.MODE_OFF,
            id="mode",
        ),
        pytest.param(
            Controls(dry_run=True, global_level=ControlLevel(maintenance_lock=True)),
            WindowState(),
            fire(),
            ReasonCode.MAINTENANCE_LOCK,
            id="lock",
        ),
        pytest.param(
            DRY_RUN,
            WindowState(person_at_window=PersonAtWindowDam(ends_at=LATER)),
            storm(),
            ReasonCode.PERSON_AT_WINDOW,
            id="person-dam",
        ),
        pytest.param(
            DRY_RUN,
            WindowState(
                manual_override=ManualOverrideDam(NOW, OverrideEndRule.ROOM_EMPTY)
            ),
            night(),
            ReasonCode.MANUAL_OVERRIDE,
            id="override-dam",
        ),
    ],
)
def test_a_wish_that_another_rule_holds_back_shows_that_rules_reason(
    controls: Controls, state: WindowState, sources: dict[str, Any], reason: ReasonCode
) -> None:
    """The outcome is hypothetical, and it names the rule that would have decided."""
    world = snapshot(sources=sources, state=state, controls=controls)
    gate = _gate(engine().recompute(world))

    assert gate.reason is reason
    assert gate.rule is not GateRule.DRY_RUN
    assert gate.dry_run is True
    assert gate.would_send == ()
    assert engine().state_after(world, engine().recompute(world)) == state


def test_target_reached_compares_with_the_real_position() -> None:
    """The other controller has put the window where the integration wanted it."""
    gate = _gate(
        engine().recompute(snapshot(sources=night(), position=1, controls=DRY_RUN))
    )

    assert gate == GateOutcome.suppress(
        GateRule.TARGET_REACHED, ReasonCode.TARGET_REACHED, dry_run=True
    )


def test_an_armed_window_is_never_marked_as_dry_run() -> None:
    """The flag belongs to the hypothetical outcome."""
    armed = _gate(
        engine().recompute(
            snapshot(
                sources=night(),
                state=WindowState(person_at_window=PersonAtWindowDam(ends_at=LATER)),
            )
        )
    )

    assert armed.dry_run is False


# --- Simulated commands -------------------------------------------------------------


def test_a_would_be_send_is_remembered_as_a_simulated_command() -> None:
    """With target, direction, time and wish class, apart from the real state."""
    world = snapshot(sources=night(), position=70, controls=DRY_RUN)

    state = engine().state_after(world, engine().recompute(world))

    assert state.simulated is not None
    (command,) = state.simulated.commands
    assert command.member_id == LEFT
    assert command.command == OwnCommand(
        command_id=command.command.command_id,
        target=Position(0),
        direction=TravelDirection.DOWN,
        time=NOW,
        wish_class=WishClass.COMFORT,
    )
    assert state.simulated.last_comfort_movement == NOW
    assert replace(state, simulated=None) == world.state
    assert WindowState.from_data(state.to_data()) == state


@pytest.mark.parametrize(
    ("position", "target", "direction"),
    [
        (20, 100, TravelDirection.UP),
        (None, 100, TravelDirection.UP),
        (None, 30, TravelDirection.DOWN),
        (60, 30, TravelDirection.DOWN),
    ],
)
def test_the_direction_of_a_simulated_command(
    position: int | None, target: int, direction: TravelDirection
) -> None:
    """From the reported position; without one, from the half the target lies in."""
    sources = day(shading_position=SourceValue.of(target))
    world = snapshot(sources=sources, position=position, controls=DRY_RUN)

    state = engine().state_after(world, engine().recompute(world))

    assert simulated_state(state).commands[0].command.direction is direction


def test_the_real_motor_protection_clock_and_the_real_commands_are_never_touched() -> (
    None
):
    """Neither read for the judgement nor written afterwards."""
    real = WindowState(
        members=(
            MemberState(
                LEFT,
                last_own_command=OwnCommand(
                    "command-1",
                    Position(30),
                    TravelDirection.DOWN,
                    NOW - timedelta(seconds=5),
                    WishClass.COMFORT,
                ),
            ),
        ),
        last_comfort_movement=NOW - timedelta(seconds=5),
    )
    world = snapshot(sources=night(), state=real, controls=DRY_RUN)

    decision = engine().recompute(world)
    after = engine().state_after(world, decision)

    # An armed window would answer `movement_in_flight` here.
    assert _gate(decision) == _would_send(0)
    assert after.members == real.members
    assert after.last_comfort_movement == real.last_comfort_movement
    assert replace(after, simulated=None) == real


def test_a_protection_would_be_send_leaves_the_simulated_comfort_clock_alone() -> None:
    """The clock is that of comfort movements."""
    earlier = NOW - timedelta(hours=1)
    state = WindowState(simulated=SimulatedState(last_comfort_movement=earlier))
    world = snapshot(sources=storm(), state=state, controls=DRY_RUN)

    after = engine().state_after(world, engine().recompute(world))

    assert simulated_state(after).last_comfort_movement == earlier
    assert simulated_state(after).commands[0].command.wish_class is WishClass.PROTECTION


def test_a_new_comfort_wish_is_judged_by_the_simulated_clock() -> None:
    """The minimum interval is reported as for an armed window."""
    subject = engine()
    morning = snapshot(sources=day(), position=50, controls=DRY_RUN)
    _, state = _run(subject, morning)
    evening = replace(
        morning, sources=night(), time=NOW + timedelta(minutes=4), state=state
    )
    much_later = replace(evening, time=NOW + timedelta(minutes=10))

    assert _gate(subject.recompute(evening)) == GateOutcome.defer(
        GateRule.MOTOR_PROTECTION,
        ReasonCode.MIN_INTERVAL,
        until=NOW + timedelta(minutes=10),
        dry_run=True,
    )
    assert subject.state_after(evening, subject.recompute(evening)) == state
    assert _gate(subject.recompute(much_later)) == _would_send(0)


def test_a_new_comfort_wish_waits_for_the_simulated_movement() -> None:
    """Twelve seconds after a would-be opening, another target is in flight."""
    no_interval = MotorProtectionSettings(min_interval=timedelta(0))
    subject = engine(window(motor_protection=no_interval))
    morning = snapshot(sources=day(), position=50, controls=DRY_RUN)
    _, state = _run(subject, morning)
    evening = replace(
        morning, sources=night(), time=NOW + timedelta(seconds=12), state=state
    )

    assert _gate(subject.recompute(evening)) == GateOutcome.defer(
        GateRule.MOVEMENT_IN_FLIGHT,
        ReasonCode.MOVEMENT_IN_FLIGHT,
        reevaluate_no_later_than=NOW + timedelta(seconds=20),
        dry_run=True,
    )


def test_what_another_controller_moves_is_not_the_windows_own_movement() -> None:
    """A dry-run window is judged by its simulated commands only."""
    world = snapshot(
        sources=night(), observation=observed(left="down:60"), controls=DRY_RUN
    )

    assert _gate(engine().recompute(world)) == _would_send(0)


def test_only_a_would_be_send_is_remembered() -> None:
    """Not a decision of an armed window, and not a decision without a gate."""
    armed = snapshot(sources=night())
    held = snapshot(
        sources=day(), state=WindowState(fire_unacknowledged=True), controls=DRY_RUN
    )

    for world in (armed, held):
        assert remember_would_be_send(world, engine().recompute(world)) is world.state


def test_the_standing_command_is_the_one_with_the_targets_of_the_wish() -> None:
    """Every member that is to be sent has a simulated command with its target."""
    world = snapshot(
        sources=night(), observation=observed(left=80, right=70), controls=DRY_RUN
    )
    subject = engine(window(LEFT, RIGHT))
    _, state = _run(subject, world)
    both = (MemberTarget(LEFT, Position(0)), MemberTarget(RIGHT, Position(0)))

    comfort = WishClass.COMFORT
    assert is_standing(simulated_state(state), both, comfort) is True
    assert is_standing(simulated_state(state), both[:1], comfort) is True
    assert is_standing(simulated_state(state), both, WishClass.PROTECTION) is False
    assert (
        is_standing(simulated_state(state), (MemberTarget(LEFT, Position(5)),), comfort)
        is False
    )
    assert is_standing(SimulatedState(), both, comfort) is False


# --- Take-over in dry-run -----------------------------------------------------------


def test_in_dry_run_a_take_over_happens_on_the_simulated_commands_only() -> None:
    """A storm begins twelve seconds after a would-be evening closing."""
    subject = engine()
    real = WindowState(
        members=(
            MemberState(
                LEFT,
                last_own_command=OwnCommand(
                    "command-1",
                    Position(0),
                    TravelDirection.DOWN,
                    NOW,
                    WishClass.COMFORT,
                ),
            ),
        ),
        owner=PositionOwner.USER,
    )
    evening = snapshot(sources=night(), position=100, state=real, controls=DRY_RUN)
    _, state = _run(subject, evening)
    stormy = replace(
        evening, sources=storm(), time=NOW + timedelta(seconds=12), state=state
    )

    decision = subject.recompute(stormy)
    after = subject.state_after(stormy, decision)

    assert _gate(decision) == GateOutcome.suppress(
        GateRule.MOVEMENT_IN_FLIGHT, ReasonCode.MOVEMENT_TAKEN_OVER, dry_run=True
    )
    assert simulated_state(after).commands[0].command.wish_class is WishClass.PROTECTION
    assert simulated_state(after).commands[0].command.time == NOW
    assert after.members == real.members
    assert after.owner is PositionOwner.USER
    # The simulated command is the storm's own now: the record is stable again.
    records, final = _run(subject, replace(stormy, state=after), times=20)
    assert set(records) == {records[0]}
    assert _gate(records[0]) == _would_send(0)
    assert final == after


def test_after_the_window_a_higher_class_would_have_sent_anew() -> None:
    """The simulated comfort command is no longer pending when the storm begins."""
    subject = engine()
    evening = snapshot(sources=night(), position=100, controls=DRY_RUN)
    _, state = _run(subject, evening)
    stormy = replace(
        evening, sources=storm(), time=NOW + timedelta(minutes=5), state=state
    )

    decision = subject.recompute(stormy)
    after = subject.state_after(stormy, decision)

    assert _gate(decision) == _would_send(0)
    command = simulated_state(after).commands[0].command
    assert command.wish_class is WishClass.PROTECTION
    assert command.time == NOW + timedelta(minutes=5)
    assert simulated_state(after).last_comfort_movement == NOW


# --- The record is stable -----------------------------------------------------------


@pytest.mark.parametrize(
    "step",
    [timedelta(0), timedelta(seconds=7), timedelta(minutes=3)],
    ids=["same-instant", "during-the-travel", "across-the-interval"],
)
@pytest.mark.parametrize("sources", [night(), storm(), fire()])
def test_one_hundred_recomputes_under_constant_inputs_give_one_record(
    sources: dict[str, Any], step: timedelta
) -> None:
    """It does not flap because of its own simulated command."""
    world = snapshot(sources=sources, position=60, controls=DRY_RUN)

    decisions, state = _run(engine(), world, times=100, step=step)

    assert len(set(decisions)) == 1
    assert _gate(decisions[0]).would_send
    assert len(simulated_state(state).commands) == 1
    assert simulated_state(state).commands[0].command.time == NOW
    # No dam was armed, the owner and the real clock are what they were.
    assert replace(state, simulated=None) == WindowState()


def test_a_recompute_that_changes_nothing_writes_nothing() -> None:
    """The state after the second recompute is the state after the first."""
    world = snapshot(sources=night(), controls=DRY_RUN)
    subject = engine()

    first = subject.state_after(world, subject.recompute(world))
    again = replace(world, time=NOW + timedelta(minutes=1), state=first)
    second = subject.state_after(again, subject.recompute(again))

    assert second is first


def test_a_simulated_day_with_constant_conditions_has_one_record_per_phase() -> None:
    """A day, then a night, then a day: three would-be sends, nothing in between."""
    subject = engine()
    start = datetime(2026, 1, 15, 8, 0, tzinfo=NOW.tzinfo)
    state = WindowState()
    records: list[GateOutcome] = []
    for minute in range(0, 24 * 60, 5):
        at = start + timedelta(minutes=minute)
        sources = day() if minute < 9 * 60 or minute >= 22 * 60 else night()
        world = replace(
            snapshot(sources=sources, position=50, state=state, controls=DRY_RUN),
            time=at,
        )
        decision = subject.recompute(world)
        state = subject.state_after(world, decision)
        if not records or records[-1] != _gate(decision):
            records.append(_gate(decision))

    assert records == [_would_send(100), _would_send(0), _would_send(100)]


# --- Arming -------------------------------------------------------------------------


def test_arming_discards_the_simulated_state_and_starts_clean() -> None:
    """No dam, nobody owns the position, and everything else stays."""
    world = snapshot(sources=night(), controls=DRY_RUN)
    dry = replace(
        engine().state_after(world, engine().recompute(world)),
        owner=PositionOwner.USER,
        person_at_window=PersonAtWindowDam(ends_at=LATER),
        manual_override=ManualOverrideDam(NOW, OverrideEndRule.ROOM_EMPTY),
        fire_unacknowledged=True,
    )

    armed = Engine.arm(dry)

    assert dry.simulated is not None
    assert armed == WindowState(fire_unacknowledged=True)
    assert arm(WindowState()) == WindowState()


def test_an_armed_window_ignores_simulated_state_that_was_left_behind() -> None:
    """The real state decides as soon as the window is armed."""
    world = snapshot(sources=night(), controls=DRY_RUN)
    left_behind = engine().state_after(world, engine().recompute(world))

    gate = _gate(engine().recompute(snapshot(sources=night(), state=left_behind)))

    assert gate == GateOutcome.send()
