"""The controls a person sets: pause, maintenance lock, operating mode, dry-run.

Pause, maintenance lock and operating mode exist on three levels: for the
whole installation ("global"), for a group and for a window. This module only
carries the three levels; which value is in effect for a window (the most
restrictive one) is decided by the arbiter.
"""

from dataclasses import dataclass
from enum import StrEnum, unique

from ._validation import require_type


@unique
class OperatingMode(StrEnum):
    """The operating modes. What each one holds back is a table of the arbiter."""

    AUTOMATIC = "automatic"
    PROTECTION_ONLY = "protection_only"
    OFF = "off"


@dataclass(frozen=True, slots=True)
class ControlLevel:
    """Pause, maintenance lock and operating mode as set on one level."""

    paused: bool = False
    maintenance_lock: bool = False
    mode: OperatingMode = OperatingMode.AUTOMATIC

    def __post_init__(self) -> None:
        """Validate the types."""
        require_type(self.paused, bool, "the pause of a control level")
        require_type(
            self.maintenance_lock, bool, "the maintenance lock of a control level"
        )
        require_type(self.mode, OperatingMode, "the operating mode of a control level")


@dataclass(frozen=True, slots=True)
class Controls:
    """What is set for one window at the moment of a recompute.

    ``dry_run`` has no default on purpose: whether a window may move is never
    assumed. A window that was never armed is in dry-run. A level on which
    nothing is set is the neutral ``ControlLevel()``.
    """

    dry_run: bool
    window_level: ControlLevel = ControlLevel()
    group_level: ControlLevel = ControlLevel()
    global_level: ControlLevel = ControlLevel()

    def __post_init__(self) -> None:
        """Validate the types."""
        require_type(self.dry_run, bool, "the dry-run flag of the controls")
        for level in self.levels:
            require_type(level, ControlLevel, "a level of the controls")

    @property
    def levels(self) -> tuple[ControlLevel, ControlLevel, ControlLevel]:
        """Return the three levels: global, group, window."""
        return (self.global_level, self.group_level, self.window_level)
