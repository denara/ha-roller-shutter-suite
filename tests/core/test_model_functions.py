"""The closed list of function identifiers and their fault behavior."""

import pytest

from custom_components.roller_shutter_suite.core.model import FaultBehavior, FunctionId

MEMBERS = [
    ("SCHEDULE", "schedule", FaultBehavior.PAUSE),
    ("SLEEP", "sleep", FaultBehavior.PAUSE),
    ("REQUEST", "request", FaultBehavior.PAUSE),
    ("PRIVACY", "privacy", FaultBehavior.PAUSE),
    ("SHADING", "shading", FaultBehavior.PAUSE),
    ("SOLAR_HEATING", "solar_heating", FaultBehavior.PAUSE),
    ("VENTILATION", "ventilation", FaultBehavior.FALL_BACK),
    ("FIRE", "fire", FaultBehavior.FALL_BACK),
    ("PROTECTION_EVENTS", "protection_events", FaultBehavior.FALL_BACK),
    ("LOCKOUT", "lockout", FaultBehavior.FALL_BACK),
    ("FROST", "frost", FaultBehavior.FALL_BACK),
    ("MOTOR_PROTECTION", "motor_protection", FaultBehavior.FALL_BACK),
    ("COMMAND_VERIFICATION", "command_verification", FaultBehavior.FALL_BACK),
    ("MANUAL_OVERRIDE", "manual_override", FaultBehavior.FALL_BACK),
]


def test_the_fault_behaviors() -> None:
    """Fall back or pause, named by what happens and not by a wish class."""
    assert [(b.name, b.value) for b in FaultBehavior] == [
        ("FALL_BACK", "fall_back"),
        ("PAUSE", "pause"),
    ]


def test_the_functions_with_their_names_values_and_order() -> None:
    """Two blocks define this list identically; this pins names, values and order."""
    assert [(f.name, f.value) for f in FunctionId] == [
        (name, value) for name, value, _ in MEMBERS
    ]


def test_every_function_has_its_fault_behavior() -> None:
    """Only a function that creates wishes is paused; ventilation restricts."""
    for name, _, behavior in MEMBERS:
        assert FunctionId[name].fault_behavior is behavior, name


def test_the_list_is_closed() -> None:
    """A free string is no function."""
    with pytest.raises(ValueError, match="not a valid FunctionId"):
        FunctionId("heating")
