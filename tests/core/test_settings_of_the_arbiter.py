"""The settings of frost protection, motor protection and the gate, as stored data.

The order of the levels, provenance and the handling of faults are tested once
for all settings in ``test_settings.py``. Here: what the stored form of these
settings accepts and refuses, and that they reach the window configuration.
"""

from datetime import timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.model import (
    FrostSettings,
    FunctionId,
    MotorProtectionSettings,
    Position,
)
from custom_components.roller_shutter_suite.core.settings import (
    WINDOW_SETTINGS,
    FaultAction,
    GroupLevel,
    Level,
    SettingKind,
    WindowResolution,
    resolve_window,
    settings_from_stored,
)
from tests.core.arbiter_kit import window

EXPECTED = {
    "frost_source": (SettingKind.OPTIONAL_REFERENCE, FunctionId.FROST),
    "frost_threshold": (SettingKind.NUMBER, FunctionId.FROST),
    "frost_hysteresis": (SettingKind.NUMBER, FunctionId.FROST),
    "frost_position": (SettingKind.NUMBER, FunctionId.FROST),
    "frost_applies_to_protection": (SettingKind.BOOLEAN, FunctionId.FROST),
    "frost_hold_closed": (SettingKind.BOOLEAN, FunctionId.FROST),
    "motor_min_change": (SettingKind.NUMBER, FunctionId.MOTOR_PROTECTION),
    "motor_min_interval": (SettingKind.DURATION, FunctionId.MOTOR_PROTECTION),
    "reevaluate_after": (SettingKind.DURATION, FunctionId.COMMAND_VERIFICATION),
}


def _resolve(
    *,
    house: dict[str, Any] | None = None,
    group: dict[str, Any] | None = None,
    own: dict[str, Any] | None = None,
) -> WindowResolution:
    return resolve_window(
        window_id="window.example",
        members=window().members,
        global_settings=settings_from_stored(house or {}, WINDOW_SETTINGS),
        group=GroupLevel(
            "group.example", settings_from_stored(group or {}, WINDOW_SETTINGS)
        ),
        window_settings=settings_from_stored(own or {}, WINDOW_SETTINGS),
    )


def test_every_setting_of_the_block_has_its_kind_and_a_function_that_falls_back() -> (
    None
):
    """Frost and motor protection restrict movement, so a fault never pauses them."""
    definitions = {
        definition.key: definition for definition in WINDOW_SETTINGS.definitions
    }

    for key, (kind, function) in EXPECTED.items():
        assert definitions[key].kind is kind, key
        assert definitions[key].function is function, key
        assert definitions[key].inheritable is True, key
        assert definitions[key].requires is None, key


def test_without_stored_settings_the_window_has_the_built_in_defaults() -> None:
    """Frost protection is not configured; 5 percent, 10 minutes, 5 minutes."""
    resolution = _resolve()

    assert resolution.config is not None
    assert resolution.config.frost == FrostSettings()
    assert resolution.config.motor_protection == MotorProtectionSettings()
    assert resolution.config.reevaluate_after == timedelta(minutes=5)
    assert resolution.settings.faults == ()


def test_each_setting_is_inherited_on_its_own() -> None:
    """The source from the house, the threshold from the group, the rest per window."""
    resolution = _resolve(
        house={"frost_source": "outdoor_temperature", "motor_min_interval": 300},
        group={"frost_threshold": 1.5, "frost_position": 85},
        own={
            "frost_hysteresis": 2,
            "frost_applies_to_protection": True,
            "frost_hold_closed": True,
            "motor_min_change": 0,
            "reevaluate_after": 120,
        },
    )

    assert resolution.settings.faults == ()
    assert resolution.config is not None
    assert resolution.config.frost == FrostSettings(
        "outdoor_temperature", 1.5, 2.0, Position(85), True, True
    )
    assert resolution.config.motor_protection == MotorProtectionSettings(
        0, timedelta(minutes=5)
    )
    assert resolution.config.reevaluate_after == timedelta(minutes=2)
    assert resolution.settings.values["frost_source"].level is Level.GLOBAL
    assert resolution.settings.values["frost_threshold"].level is Level.GROUP
    assert resolution.settings.values["frost_hysteresis"].level is Level.WINDOW


def test_a_window_can_switch_inherited_frost_protection_off() -> None:
    """The stored form "explicitly none" on the optional reference beats the house."""
    resolution = _resolve(
        house={"frost_source": "outdoor_temperature"}, own={"frost_source": "__none__"}
    )

    assert resolution.config is not None
    assert resolution.config.frost.source is None
    assert resolution.settings.faults == ()


@pytest.mark.parametrize(
    ("key", "stored"),
    [
        ("frost_threshold", "cold"),
        ("frost_threshold", True),
        ("frost_hysteresis", -1),
        ("frost_position", 101),
        ("frost_position", 89.5),
        ("frost_applies_to_protection", "yes"),
        ("frost_hold_closed", 1),
        ("frost_source", 7),
        ("motor_min_change", 101),
        ("motor_min_change", 2.5),
        ("motor_min_interval", -1),
        ("motor_min_interval", "10 minutes"),
        ("reevaluate_after", 0),
        ("reevaluate_after", 366 * 24 * 60 * 60 + 1),
        ("frost_threshold", "__none__"),
    ],
)
def test_a_faulty_stored_value_falls_back_and_pauses_nothing(
    key: str, stored: object
) -> None:
    """The value of the next level applies, the fault is reported, comfort goes on."""
    good = {
        "frost_source": "outdoor_temperature",
        "frost_threshold": 1.5,
        "frost_hysteresis": 2,
        "frost_position": 85,
        "frost_applies_to_protection": True,
        "frost_hold_closed": True,
        "motor_min_change": 3,
        "motor_min_interval": 300,
        "reevaluate_after": 120,
    }
    resolution = _resolve(group=good, own={key: stored})
    expected = _resolve(group=good)

    assert resolution.config == expected.config
    assert resolution.config is not None
    assert resolution.config.disabled_functions == frozenset()
    (fault,) = resolution.settings.faults
    assert (fault.key, fault.level) == (key, Level.WINDOW)
    assert fault.action is FaultAction.FELL_BACK
