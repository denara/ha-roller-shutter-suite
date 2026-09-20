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
    NEVER_SKIPPED,
    GateRuleRegistration,
    skips,
)
from custom_components.roller_shutter_suite.core.model import (
    FULLY_OPEN,
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


def test_the_bypass_lists_exactly_the_rules_of_the_design_specification() -> None:
    """Section 2.4 names the rules by their number in the table of section 2.3."""
    text = ARCHITECTURE.read_text(encoding="utf-8")
    section = text.split("### 2.4 The fire bypass")[1].split("### 2.5")[0]
    skipped = section.split("It does **not** skip:")[0]
    numbers = {int(number) for number in re.findall(r"(?:^- |, )(\d+) ", skipped, re.M)}
    rules = list(GateRule)

    assert {rules[number - 1] for number in numbers} == FIRE_BYPASS
    assert len(FIRE_BYPASS) == 8  # noqa: PLR2004 - rules 4 to 11
    assert {
        GateRule.MAINTENANCE_LOCK,
        GateRule.NO_MEMBER_CAN_EXECUTE,
        GateRule.TARGET_REACHED,
        GateRule.DRY_RUN,
    } == NEVER_SKIPPED


def test_only_fire_skips_and_only_the_listed_rules() -> None:
    """Never the maintenance lock, never dry-run."""
    for rule in GateRule:
        assert skips(WishClass.FIRE, rule) is (rule in FIRE_BYPASS)
        assert skips(WishClass.PROTECTION, rule) is False
        assert skips(WishClass.COMFORT, rule) is False
    assert skips(WishClass.FIRE, GateRule.MAINTENANCE_LOCK) is False
    assert skips(WishClass.FIRE, GateRule.DRY_RUN) is False


def test_the_registry_keeps_the_bypass_exact_in_both_directions() -> None:
    """No bypassed rule can claim fire; no other rule can let a class off."""
    for registration in BUILT_IN_GATE_RULES:
        in_bypass = registration.rule in FIRE_BYPASS
        assert (WishClass.FIRE in registration.applies_to) is not in_bypass
    with pytest.raises(ValueError, match="part of the fire bypass"):
        GateRuleRegistration(GateRule.PAUSE, ALL_CLASSES, lambda _gate: None)
    with pytest.raises(ValueError, match="is never skipped"):
        GateRuleRegistration(
            GateRule.DRY_RUN,
            frozenset({WishClass.PROTECTION, WishClass.COMFORT}),
            lambda _gate: None,
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


# --- Property: fire is sent unless maintenance lock or dry-run is active -------------

_COMMAND = OwnCommand(
    "command-1",
    Position(30),
    TravelDirection.DOWN,
    NOW - timedelta(seconds=3),
    WishClass.COMFORT,
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
    # (position, movement in flight, inside the minimum interval)
    (0, False, False),
    (97, False, True),  # below the minimum change, and inside the interval
    (40, True, True),  # a pending own command and a member that reports a movement
]


def test_fire_is_sent_in_every_combination_unless_lock_or_dry_run_is_active() -> None:
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
    assert len(combinations) == 3 * 2 * 3 * 2 * 3 * 3 * 2 * 2

    for situation in combinations:
        mode, paused, level, person, override, motor, locked, dry_run = situation
        position, in_flight, inside_interval = motor
        clock = NOW - timedelta(seconds=3) if inside_interval else None
        # An armed window is judged by its real commands and its real clock, a
        # window in dry-run by the simulated ones: give each what it looks at.
        state = WindowState(
            members=(
                (MemberState(LEFT, last_own_command=_COMMAND),) if in_flight else ()
            ),
            person_at_window=person,
            manual_override=override,
            last_comfort_movement=clock,
            simulated=SimulatedState(
                commands=(MemberCommand(LEFT, _COMMAND),) if in_flight else (),
                last_comfort_movement=clock,
            ),
        )
        controls = Controls(
            dry_run=dry_run,
            **{level: ControlLevel(paused=paused, maintenance_lock=locked, mode=mode)},
        )
        observation = observed(left=f"down:{position}" if in_flight else position)

        decision = subject.recompute(
            snapshot(
                sources=fire(), observation=observation, state=state, controls=controls
            )
        )

        assert decision.winning_wish is not None, situation
        assert decision.winning_wish.reason is ReasonCode.FIRE_ALARM, situation
        assert decision.target == FULLY_OPEN, situation
        if locked:
            expected = GateOutcome.suppress(
                GateRule.MAINTENANCE_LOCK, ReasonCode.MAINTENANCE_LOCK, dry_run=dry_run
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
