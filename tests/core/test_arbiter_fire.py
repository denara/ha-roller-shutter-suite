"""The fire bypass: a named construct, and fire is sent whatever else holds."""

import itertools
import re
from datetime import timedelta
from pathlib import Path

import pytest

from custom_components.roller_shutter_suite.core.arbiter import (
    ALL_CLASSES,
    BUILT_IN_GATE_RULES,
    FIRE_BYPASS,
    NEVER_BYPASSED,
    GateRuleRegistration,
    bypassed_rules,
    skips,
)
from custom_components.roller_shutter_suite.core.model import (
    FULLY_OPEN,
    GATE_RULE_REASONS,
    ControlLevel,
    Controls,
    FrostSettings,
    GateOutcome,
    GateRule,
    ManualOverrideDam,
    MemberCommand,
    MemberState,
    MemberTarget,
    OperatingMode,
    OverrideEndRule,
    OwnCommand,
    PersonAtWindowDam,
    Position,
    SimulatedState,
    SourceValue,
    TravelDirection,
    WindowState,
    WishClass,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import (
    LEFT,
    NOW,
    engine,
    fire,
    night,
    observed,
    snapshot,
    window,
)

ARCHITECTURE = Path(__file__).parents[2] / "docs" / "architecture.md"


def test_the_bypass_touches_exactly_the_rules_the_design_specification_lists() -> None:
    """Section 2.4 names the rules by their number in the table of section 2.3."""
    text = ARCHITECTURE.read_text(encoding="utf-8")
    section = text.split("### 2.4 The fire bypass")[1].split("### 2.5")[0]
    skipped = section.split("It does **not** skip:")[0]
    numbers = {int(number) for number in re.findall(r"(?:^- |, )(\d+) ", skipped, re.M)}
    rules = list(GateRule)

    assert {rules[number - 1] for number in numbers} == bypassed_rules()
    assert len(bypassed_rules()) == 8  # noqa: PLR2004 - rules 4 to 11


def test_fire_skips_whole_rules_except_movement_in_flight() -> None:
    """Of that rule it skips the deferral only, never the duplicate suppression."""
    in_flight = GATE_RULE_REASONS[GateRule.MOVEMENT_IN_FLIGHT]

    for rule in bypassed_rules() - {GateRule.MOVEMENT_IN_FLIGHT}:
        assert GATE_RULE_REASONS[rule] <= FIRE_BYPASS, rule
    assert in_flight & FIRE_BYPASS == {ReasonCode.MOVEMENT_IN_FLIGHT}
    assert in_flight & NEVER_BYPASSED == {
        ReasonCode.DUPLICATE_COMMAND,
        ReasonCode.MOVEMENT_TAKEN_OVER,
    }
    assert {
        ReasonCode.MAINTENANCE_LOCK,
        ReasonCode.DRY_RUN,
        ReasonCode.COVER_UNAVAILABLE,
        ReasonCode.CAPABILITY_MISSING,
        ReasonCode.TARGET_REACHED,
    } <= NEVER_BYPASSED
    assert not FIRE_BYPASS & NEVER_BYPASSED


def test_only_fire_skips_and_only_what_the_bypass_names() -> None:
    """Never the maintenance lock, never dry-run."""
    for registration in BUILT_IN_GATE_RULES:
        bypassed = registration.reasons <= FIRE_BYPASS
        assert skips(WishClass.FIRE, registration.reasons) is bypassed
        assert skips(WishClass.PROTECTION, registration.reasons) is False
        assert skips(WishClass.COMFORT, registration.reasons) is False
    assert skips(WishClass.FIRE, GATE_RULE_REASONS[GateRule.MAINTENANCE_LOCK]) is False
    assert skips(WishClass.FIRE, GATE_RULE_REASONS[GateRule.DRY_RUN]) is False
    assert (
        skips(WishClass.FIRE, GATE_RULE_REASONS[GateRule.MOVEMENT_IN_FLIGHT]) is False
    )


def test_the_registry_keeps_the_bypass_exact_in_both_directions() -> None:
    """No bypassed part can claim fire; no other part can let a class off."""
    for registration in BUILT_IN_GATE_RULES:
        bypassed = registration.reasons <= FIRE_BYPASS
        assert (WishClass.FIRE in registration.applies_to) is not bypassed
    with pytest.raises(ValueError, match="part of the fire bypass"):
        GateRuleRegistration(GateRule.PAUSE, ALL_CLASSES, lambda _gate: None)
    with pytest.raises(ValueError, match="is never skipped"):
        GateRuleRegistration(
            GateRule.DRY_RUN,
            frozenset({WishClass.PROTECTION, WishClass.COMFORT}),
            lambda _gate: None,
        )
    with pytest.raises(ValueError, match="register the parts separately"):
        GateRuleRegistration(
            GateRule.MOVEMENT_IN_FLIGHT, ALL_CLASSES, lambda _gate: None
        )
    with pytest.raises(ValueError, match="gives only its own reasons"):
        GateRuleRegistration(
            GateRule.PAUSE,
            frozenset({WishClass.COMFORT}),
            lambda _gate: None,
            reasons=frozenset({ReasonCode.MIN_CHANGE}),
        )


def test_fire_is_exempt_from_every_constraint_including_frost() -> None:
    """It opens fully although frost would limit the opening to 90."""
    config = window(
        frost=FrostSettings(
            source="outdoor_temperature", applies_to_protection=True, hold_closed=True
        )
    )
    decision = engine(config).recompute(
        snapshot(sources=fire(outdoor_temperature=SourceValue.of(-8.0)), position=0)
    )

    assert decision.constraints == ()
    assert decision.target == FULLY_OPEN
    assert decision.gate == GateOutcome.send()


# --- Property: fire is sent or taken over unless lock or dry-run is active ----------


_REASON_OF = {
    WishClass.FIRE: ReasonCode.FIRE_ALARM,
    WishClass.PROTECTION: ReasonCode.PROTECTION_EVENT,
    WishClass.COMFORT: ReasonCode.SCHEDULE_DAY,
}


def _command(target: int, wish_class: WishClass, seconds_ago: float = 3) -> OwnCommand:
    return OwnCommand(
        "command-1",
        Position(target),
        TravelDirection.UP,
        NOW - timedelta(seconds=seconds_ago),
        wish_class,
        _REASON_OF[wish_class],
    )


_MODES = list(OperatingMode)
_LEVELS = ["global_level", "group_level", "window_level"]
_PERSON_DAMS = [None, PersonAtWindowDam(ends_at=NOW + timedelta(minutes=10))]
_OVERRIDE_DAMS = [
    None,
    ManualOverrideDam(
        NOW, OverrideEndRule.FIXED_MINUTES, ends_at=NOW + timedelta(minutes=30)
    ),
    ManualOverrideDam(NOW, OverrideEndRule.ROOM_EMPTY),
]
_MOTOR_PROTECTION = [
    # (position, pending own command, inside the minimum interval)
    (0, None, False),
    (97, None, True),  # below the minimum change, and inside the interval
    (40, _command(30, WishClass.COMFORT), True),  # another target: fire retargets
    (40, _command(100, WishClass.COMFORT), True),  # the same target: taken over
    (40, _command(100, WishClass.PROTECTION), False),  # the same target: taken over
]


def test_fire_is_sent_or_taken_over_in_every_combination_unless_lock_or_dry_run() -> (
    None
):
    """Mode, pause, both dams, motor protection and a movement in flight."""
    subject = engine()
    combinations = list(
        itertools.product(
            _MODES,
            [False, True],  # paused
            _LEVELS,
            _PERSON_DAMS,
            _OVERRIDE_DAMS,
            _MOTOR_PROTECTION,
            [False, True],  # maintenance lock
            [False, True],  # dry-run
        )
    )
    assert len(combinations) == 3 * 2 * 3 * 2 * 3 * 5 * 2 * 2

    for situation in combinations:
        mode, paused, level, person, override, motor, locked, dry_run = situation
        position, pending, inside_interval = motor
        clock = NOW - timedelta(seconds=3) if inside_interval else None
        # An armed window is judged by its real commands and its real clock, a
        # window in dry-run by the simulated ones: give each what it looks at.
        state = WindowState(
            members=((MemberState(LEFT, last_own_command=pending),) if pending else ()),
            person_at_window=person,
            manual_override=override,
            last_comfort_movement=clock,
            simulated=SimulatedState(
                commands=(MemberCommand(LEFT, pending),) if pending else (),
                last_comfort_movement=clock,
            ),
        )
        controls = Controls(
            dry_run=dry_run,
            **{level: ControlLevel(paused=paused, maintenance_lock=locked, mode=mode)},
        )
        observation = observed(left=f"up:{position}" if pending else position)

        decision = subject.recompute(
            snapshot(
                sources=fire(), observation=observation, state=state, controls=controls
            )
        )

        assert decision.winning_wish is not None, situation
        assert decision.winning_wish.reason is ReasonCode.FIRE_ALARM, situation
        assert decision.target == FULLY_OPEN, situation
        taken_over = pending is not None and pending.target == FULLY_OPEN
        if locked:
            expected = GateOutcome.suppress(
                GateRule.MAINTENANCE_LOCK, ReasonCode.MAINTENANCE_LOCK, dry_run=dry_run
            )
        elif taken_over:
            expected = GateOutcome.suppress(
                GateRule.MOVEMENT_IN_FLIGHT,
                ReasonCode.MOVEMENT_TAKEN_OVER,
                dry_run=dry_run,
            )
        elif dry_run:
            expected = GateOutcome.would_have_sent([MemberTarget(LEFT, FULLY_OPEN)])
        else:
            expected = GateOutcome.send()
        assert decision.gate == expected, situation


def test_the_same_combinations_do_hold_back_a_comfort_wish() -> None:
    """The property is about fire, not about rules that never apply."""
    state = WindowState(person_at_window=_PERSON_DAMS[1])

    held = engine().recompute(snapshot(sources=night(), state=state))

    assert held.gate is not None
    assert held.gate.reason is ReasonCode.PERSON_AT_WINDOW


def test_fire_is_not_sent_twice_while_its_own_command_is_pending() -> None:
    """The suppression hangs on the running expectation window."""
    pending = WindowState(
        members=(MemberState(LEFT, last_own_command=_command(100, WishClass.FIRE)),)
    )

    gate = (
        engine()
        .recompute(
            snapshot(sources=fire(), observation=observed(left="up:40"), state=pending)
        )
        .gate
    )

    assert gate == GateOutcome.suppress(
        GateRule.MOVEMENT_IN_FLIGHT, ReasonCode.DUPLICATE_COMMAND
    )


@pytest.mark.parametrize("paused", [False, True])
def test_fire_is_sent_again_as_soon_as_the_window_of_an_unfinished_command_has_closed(
    paused: bool,
) -> None:
    """Up takes 20 seconds here. No backoff, no waiting: at once."""
    controls = Controls(
        dry_run=False,
        window_level=ControlLevel(paused=paused, mode=OperatingMode.OFF),
    )

    def gate(seconds_ago: float) -> GateOutcome | None:
        command = _command(100, WishClass.FIRE, seconds_ago)
        state = WindowState(
            members=(MemberState(LEFT, last_own_command=command),),
            last_comfort_movement=NOW,
        )
        world = snapshot(sources=fire(), position=40, state=state, controls=controls)
        return engine().recompute(world).gate

    assert gate(19.9) == GateOutcome.suppress(
        GateRule.MOVEMENT_IN_FLIGHT, ReasonCode.DUPLICATE_COMMAND
    )
    assert gate(20) == GateOutcome.send()
    assert gate(3600) == GateOutcome.send()


def test_a_fire_command_that_reached_its_target_is_not_repeated() -> None:
    """The window is open: the target is reached, whatever the window says."""
    state = WindowState(
        members=(MemberState(LEFT, last_own_command=_command(100, WishClass.FIRE)),)
    )

    gate = engine().recompute(snapshot(sources=fire(), position=100, state=state)).gate

    assert gate is not None
    assert gate.reason is ReasonCode.TARGET_REACHED
