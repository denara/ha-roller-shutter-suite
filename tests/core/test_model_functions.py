"""The closed list of function identifiers and their classes."""

import pytest

from custom_components.roller_shutter_suite.core.model import FunctionClass, FunctionId

COMFORT = [
    ("SCHEDULE", "schedule"),
    ("SLEEP", "sleep"),
    ("REQUEST", "request"),
    ("PRIVACY", "privacy"),
    ("SHADING", "shading"),
    ("SOLAR_HEATING", "solar_heating"),
    ("VENTILATION", "ventilation"),
]
PROTECTION = [
    ("FIRE", "fire"),
    ("PROTECTION_EVENTS", "protection_events"),
    ("LOCKOUT", "lockout"),
    ("FROST", "frost"),
    ("MOTOR_PROTECTION", "motor_protection"),
    ("COMMAND_VERIFICATION", "command_verification"),
    ("MANUAL_OVERRIDE", "manual_override"),
]


def test_the_function_classes() -> None:
    """Protection and comfort, nothing else."""
    assert [(c.name, c.value) for c in FunctionClass] == [
        ("PROTECTION", "protection"),
        ("COMFORT", "comfort"),
    ]


def test_the_functions_with_their_names_values_and_order() -> None:
    """Two blocks define this list identically; this pins names, values and order."""
    assert [(f.name, f.value) for f in FunctionId] == COMFORT + PROTECTION


def test_every_function_has_its_class() -> None:
    """The class is a property of the function."""
    for name, _ in COMFORT:
        assert FunctionId[name].function_class is FunctionClass.COMFORT
    for name, _ in PROTECTION:
        assert FunctionId[name].function_class is FunctionClass.PROTECTION


def test_the_list_is_closed() -> None:
    """A free string is no function."""
    with pytest.raises(ValueError, match="not a valid FunctionId"):
        FunctionId("heating")
