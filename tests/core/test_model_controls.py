"""Controls of a window, and the settings the arbiter block adds to a window."""

from datetime import timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.model import (
    CapabilityProfile,
    ControlLevel,
    Controls,
    FrostSettings,
    MemberConfig,
    MotorProtectionSettings,
    OperatingMode,
    Position,
    WindowConfig,
)


def window(**changes: Any) -> WindowConfig:
    """Return a window with one member that can do and report everything."""
    capabilities = CapabilityProfile(
        supports_open_close=True,
        supports_set_position=True,
        supports_stop=True,
        reports_position=True,
        travel_time_up=timedelta(seconds=20),
        travel_time_down=timedelta(seconds=18),
    )
    member = MemberConfig("cover.example_window", capabilities)
    return WindowConfig(window_id="window.example", members=(member,), **changes)


def test_a_control_level_is_neutral_by_default() -> None:
    """Nothing set on a level means: not paused, not locked, automatic."""
    level = ControlLevel()

    assert level.paused is False
    assert level.maintenance_lock is False
    assert level.mode is OperatingMode.AUTOMATIC


def test_controls_carry_three_levels_and_dry_run() -> None:
    """Global, group and window, in that order; dry-run is per window."""
    paused = ControlLevel(paused=True)
    controls = Controls(dry_run=True, group_level=paused)

    assert controls.levels == (ControlLevel(), paused, ControlLevel())
    assert controls == Controls(dry_run=True, group_level=ControlLevel(paused=True))
    assert hash(controls) == hash(Controls(dry_run=True, group_level=paused))


def test_dry_run_is_never_assumed() -> None:
    """Whether a window may move has no default."""
    arguments: dict[str, Any] = {}
    with pytest.raises(TypeError, match="dry_run"):
        Controls(**arguments)


def test_the_types_of_the_controls_are_checked() -> None:
    """A truthy string is not a pause."""
    bad: Any = "yes"
    with pytest.raises(TypeError, match="pause"):
        ControlLevel(paused=bad)
    with pytest.raises(TypeError, match="maintenance lock"):
        ControlLevel(maintenance_lock=bad)
    with pytest.raises(TypeError, match="operating mode"):
        ControlLevel(mode=bad)
    with pytest.raises(TypeError, match="dry-run"):
        Controls(dry_run=bad)
    with pytest.raises(TypeError, match="level"):
        Controls(dry_run=False, window_level=bad)


def test_the_operating_modes_are_a_closed_set_of_three() -> None:
    """Named profiles are not built."""
    assert [mode.value for mode in OperatingMode] == [
        "automatic",
        "protection_only",
        "off",
    ]


def test_motor_protection_defaults_and_ranges() -> None:
    """Five percent and ten minutes; zero switches a part off."""
    settings = MotorProtectionSettings()
    bad: Any = 2.5

    assert settings.min_change == 5  # noqa: PLR2004 - the documented default
    assert settings.min_interval == timedelta(minutes=10)
    assert MotorProtectionSettings(0, timedelta(0)).min_change == 0
    with pytest.raises(TypeError, match="minimum change"):
        MotorProtectionSettings(min_change=bad)
    with pytest.raises(TypeError, match="minimum change"):
        MotorProtectionSettings(min_change=True)
    with pytest.raises(ValueError, match="within 0 and 100"):
        MotorProtectionSettings(min_change=101)
    with pytest.raises(TypeError, match="minimum interval"):
        MotorProtectionSettings(min_interval=bad)
    with pytest.raises(ValueError, match="negative"):
        MotorProtectionSettings(min_interval=timedelta(seconds=-1))


def test_frost_settings_defaults_and_ranges() -> None:
    """Not configured, 0 degrees, frost position 90, comfort only, no hold."""
    settings = FrostSettings()
    bad: Any = "x"

    assert settings.source is None
    assert settings.threshold == 0.0
    assert settings.position == Position(90)
    assert settings.applies_to_protection is False
    assert settings.hold_closed is False
    with pytest.raises(ValueError, match="must not be empty"):
        FrostSettings(source="")
    with pytest.raises(TypeError, match="threshold"):
        FrostSettings(threshold=bad)
    with pytest.raises(ValueError, match="negative"):
        FrostSettings(hysteresis=-0.5)
    with pytest.raises(TypeError, match="frost position"):
        FrostSettings(position=bad)
    with pytest.raises(TypeError, match="applies to protection"):
        FrostSettings(applies_to_protection=bad)
    with pytest.raises(TypeError, match="hold closed"):
        FrostSettings(hold_closed=bad)


def test_a_window_carries_the_settings_of_the_arbiter_block() -> None:
    """Motor protection, frost, and the upper bound of an open-ended deferral."""
    config = window()
    bad: Any = "x"

    assert config.motor_protection == MotorProtectionSettings()
    assert config.frost == FrostSettings()
    assert config.reevaluate_after == timedelta(minutes=5)
    # One field per setting, so each can be inherited on its own; the two
    # views put them together and hold their value rules.
    changed = window(
        frost_source="outdoor_temperature",
        frost_threshold=1.5,
        frost_hysteresis=2.0,
        frost_position=Position(80),
        frost_applies_to_protection=True,
        frost_hold_closed=True,
        motor_min_change=3,
        motor_min_interval=timedelta(minutes=2),
    )
    assert changed.frost == FrostSettings(
        "outdoor_temperature", 1.5, 2.0, Position(80), True, True
    )
    assert changed.motor_protection == MotorProtectionSettings(3, timedelta(minutes=2))
    with pytest.raises(TypeError, match="minimum change"):
        window(motor_min_change=bad)
    with pytest.raises(ValueError, match="negative"):
        window(motor_min_interval=timedelta(seconds=-1))
    with pytest.raises(TypeError, match="frost threshold"):
        window(frost_threshold=bad)
    with pytest.raises(ValueError, match="must not be empty"):
        window(frost_source="")
    with pytest.raises(TypeError, match="frost position"):
        window(frost_position=90)
    with pytest.raises(TypeError, match="re-evaluation bound"):
        window(reevaluate_after=bad)
    with pytest.raises(ValueError, match="longer than zero"):
        window(reevaluate_after=timedelta(0))
