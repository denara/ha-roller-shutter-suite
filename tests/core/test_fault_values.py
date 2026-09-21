"""The two generic tests of the fault values, over the registry of the window.

Decision 15: no restriction is ever lifted by a data fault, and a data fault
never takes protection away.

1. **The mandatory test of the project owner.** For every setting of every
   function that falls back, a faulty value never leads to a decision that a
   valid value would have forbidden.
2. **The protection principle.** A fault value never restricts a PROTECTION
   wish more than the default does; cautious values may restrict comfort only.

Both walk ``WINDOW_SETTINGS`` and the situations of
``tests/core/fault_value_situations.py``; neither names a setting. A setting
that a later block registers is covered as soon as its function has a
situation, and a function without one fails here with advice.

**What test 1 proves.** In every comfort situation of its function, a setting
whose stored value is faulty on the only level, or that an unreadable house
level hides, never makes the window send more (a member that would not have
moved, or the same member further) than it sends with: the default; what the
situation sets; either position of a switch; "none" and a working source for
an optional reference. **What it does not prove:** that the fault value is at
least as restrictive as every number somebody could have meant. A threshold, a
position and a duration have no most restrictive value, so for them it proves
"never less restrictive than the default". It also says nothing outside the
listed situations, and nothing about a protection wish: that is test 2.

**What test 2 proves.** In every protection situation, for every such setting
(whatever its function), the protection wish decided with the fault value
sends no less than the same wish decided with the default, for a faulty value
and for an unreadable house level, where all fault values apply at once.
"""

from datetime import timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.model import (
    BLIND_SOURCE,
    FULLY_OPEN,
    FunctionId,
    GateKind,
    Position,
    WishClass,
)
from custom_components.roller_shutter_suite.core.model._data import as_str
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from custom_components.roller_shutter_suite.core.settings import (
    WINDOW_SETTINGS,
    SettingDefinition,
    SettingKind,
    SettingsRegistry,
)
from tests.core.arbiter_kit import LEFT, day
from tests.core.fault_value_situations import (
    FAULT_CASES,
    SITUATIONS,
    Situation,
    decide,
    loosened_by_a_fault,
    missing_situations,
    protection_restricted_by_a_fault,
    sent,
    tells_apart,
    with_fault_value,
)

CAUTIOUS = [
    definition
    for definition in WINDOW_SETTINGS.definitions
    if definition.falls_back_cautiously
]


def test_faulty_value_never_leads_to_a_decision_a_valid_value_would_have_forbidden() -> (
    None
):
    """Test 1, over every setting of every function that falls back."""
    findings = loosened_by_a_fault()

    assert not findings, "\n".join(findings)


def test_fault_value_never_restricts_a_protection_wish_more_than_the_default() -> None:
    """Test 2, over every such setting in every protection situation."""
    findings = protection_restricted_by_a_fault()

    assert not findings, "\n".join(findings)


# --- The tests would notice: every mutation fails them ------------------------------


@pytest.mark.parametrize(
    ("key", "less_restrictive"),
    [
        ("frost_source", None),
        ("frost_position", FULLY_OPEN),
        ("frost_hold_closed", False),
        ("frost_threshold", -1.0),
        ("frost_hysteresis", 0.2),
        ("motor_min_change", 2),
        ("motor_min_interval", timedelta(minutes=5)),
    ],
)
def test_less_restrictive_fault_value_fails_the_mandatory_test(
    key: str, less_restrictive: object
) -> None:
    """A fault value changed to a less restrictive one is found, with advice."""
    value = less_restrictive

    findings = loosened_by_a_fault(with_fault_value(key, value))

    assert findings
    assert any(finding.startswith(f"{key}: ") for finding in findings)
    assert "is less restrictive than a valid value" in findings[0]
    assert "WINDOW_SETTINGS" in findings[0]
    # The protection principle is not what such a change breaks.
    assert not protection_restricted_by_a_fault(with_fault_value(key, value))


def test_fault_value_that_restricts_protection_fails_the_protection_test() -> None:
    """A fault that switches "applies to protection" on stops a hail opening short."""
    mutated = with_fault_value("frost_applies_to_protection", True)

    findings = protection_restricted_by_a_fault(mutated)

    assert findings
    assert any(text.startswith("frost_applies_to_protection: ") for text in findings)
    assert "never restricts a protection wish more than the default" in findings[0]
    # The mandatory test alone would not mind: it judges comfort wishes.
    assert not loosened_by_a_fault(mutated)


# --- The tests are not empty ---------------------------------------------------------


def test_every_function_with_settings_that_fall_back_has_a_situation() -> None:
    """A later block that registers such a setting fails here until it adds one."""
    assert not missing_situations(), "\n".join(missing_situations())
    assert {definition.function for definition in CAUTIOUS} == {
        FunctionId.FROST,
        FunctionId.MOTOR_PROTECTION,
        FunctionId.COMMAND_VERIFICATION,
    }


def test_function_without_a_situation_is_named_with_advice() -> None:
    """Shown with a registry that has a setting of lockout protection."""
    contact = SettingDefinition[Any](
        key="lockout_contact",
        kind=SettingKind.OPTIONAL_REFERENCE,
        function=FunctionId.LOCKOUT,
        default=None,
        fault_value=BLIND_SOURCE,
        parse=as_str,
        inheritable=False,
    )

    (message,) = missing_situations(SettingsRegistry((contact,)))

    assert "'lockout' has settings that fall back (lockout_contact)" in message
    assert "Add one to SITUATIONS in tests/core/fault_value_situations.py" in message


def test_situations_have_both_classes_and_protection_really_moves() -> None:
    """Test 2 compares movements, so its situations must send with the defaults."""
    classes = {situation.wish_class for situation in SITUATIONS}
    assert classes == {WishClass.COMFORT, WishClass.PROTECTION}
    moving = [
        situation
        for situation in SITUATIONS
        if situation.wish_class is WishClass.PROTECTION
        and sent(decide(WINDOW_SETTINGS, situation, "frost_source", inherit=True))
    ]
    assert len(moving) >= 3  # noqa: PLR2004 - the hail openings with reachable members


@pytest.mark.parametrize(
    "definition",
    [
        definition
        for definition in CAUTIOUS
        if definition.kind in (SettingKind.BOOLEAN, SettingKind.OPTIONAL_REFERENCE)
    ],
    ids=lambda definition: definition.key,
)
def test_situations_tell_the_values_of_a_switch_or_a_reference_apart(
    definition: SettingDefinition[Any],
) -> None:
    """Otherwise the two tests would say nothing about that setting."""
    assert tells_apart(definition), (
        f"No situation of the function {definition.function} gives two valid "
        f"values of {definition.key!r} two different decisions. Add one to "
        "SITUATIONS in tests/core/fault_value_situations.py."
    )


# --- The cases the project owner named ----------------------------------------------

REVIEW_CASE = next(s for s in SITUATIONS if s.name.startswith("frost just below"))
HAIL_ON_CLOSED = next(
    s
    for s in SITUATIONS
    if s.name == "no frost source anywhere, hail opens a closed shutter"
)
HAIL_IN_FROST = next(
    s for s in SITUATIONS if s.name == "frost, hail opens a closed shutter"
)


@pytest.mark.parametrize("fault_case", FAULT_CASES)
def test_unreadable_frost_source_keeps_the_frost_limit(fault_case: str) -> None:
    """The case of the review: 90 with a valid source, and 90 with a faulty one."""
    valid = decide(
        WINDOW_SETTINGS,
        REVIEW_CASE,
        "frost_source",
        value=REVIEW_CASE.settings["frost_source"],
    )
    faulty = decide(WINDOW_SETTINGS, REVIEW_CASE, "frost_source", fault_case=fault_case)

    assert sent(valid) == {LEFT: Position(90)}
    assert sent(faulty) == {LEFT: Position(90)}
    assert [result.reason for result in valid.constraints] == [ReasonCode.FROST_LIMIT]
    assert [result.reason for result in faulty.constraints] == [
        ReasonCode.FROST_LIMIT_SOURCE_BLIND
    ]


@pytest.mark.parametrize("situation", [HAIL_ON_CLOSED, HAIL_IN_FROST])
def test_hail_opening_of_a_closed_shutter_goes_through_with_an_unreadable_house(
    situation: Situation,
) -> None:
    """Blind source, "hold closed" on, "applies to protection" off: untouched.

    With an unreadable house level every fault value applies at once. The
    protection opening is decided exactly as with the defaults.
    """
    default = decide(WINDOW_SETTINGS, situation, "frost_hold_closed", inherit=True)
    faulty = decide(
        WINDOW_SETTINGS, situation, "frost_hold_closed", fault_case=FAULT_CASES[1]
    )

    assert sent(default) == {LEFT: FULLY_OPEN}
    assert sent(faulty) == sent(default)
    assert faulty.constraints == default.constraints == ()
    assert faulty.gate is not None
    assert faulty.gate.kind is GateKind.SEND


def test_kit_world_of_a_calm_day_opens_so_the_situations_want_a_movement() -> None:
    """The comfort situations rest on the schedule stub that opens during the day."""
    assert day()["part_of_day"].value == "day"
