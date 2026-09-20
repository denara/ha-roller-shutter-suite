"""Operating modes as a table, and the effective controls of a window.

Pause, maintenance lock and operating mode exist on global, group and window
level. What is in effect for a window is the most restrictive of the three: a
window is paused if any level is paused, locked if any level is locked, and
its mode is the most restrictive mode of the three levels.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from custom_components.roller_shutter_suite.core.model import (
    Controls,
    OperatingMode,
    WishClass,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode


@dataclass(frozen=True, slots=True)
class ModeEntry:
    """One row of the mode table.

    - ``restrictiveness``: the rank among the modes; the higher one wins when
      the levels disagree.
    - ``holds_back``: the wish classes the mode suppresses.
    - ``reason``: the reason code of the suppression; ``None`` for a mode that
      holds nothing back.
    """

    restrictiveness: int
    holds_back: frozenset[WishClass]
    reason: ReasonCode | None


MODE_TABLE: Final = MappingProxyType(
    {
        OperatingMode.AUTOMATIC: ModeEntry(0, frozenset(), None),
        OperatingMode.PROTECTION_ONLY: ModeEntry(
            1, frozenset({WishClass.COMFORT}), ReasonCode.MODE_PROTECTION_ONLY
        ),
        OperatingMode.OFF: ModeEntry(
            2,
            frozenset({WishClass.PROTECTION, WishClass.COMFORT}),
            ReasonCode.MODE_OFF,
        ),
    }
)
"""What each operating mode holds back. No mode holds back fire.

The gate rule "operating mode" reads this table and nothing else, so a further
mode is a further row.
"""


@dataclass(frozen=True, slots=True)
class EffectiveControls:
    """What is in effect for one window after the three levels were combined."""

    paused: bool
    maintenance_lock: bool
    mode: OperatingMode
    dry_run: bool


def effective_controls(controls: Controls) -> EffectiveControls:
    """Return the most restrictive value of each control over the three levels."""
    levels = controls.levels
    return EffectiveControls(
        paused=any(level.paused for level in levels),
        maintenance_lock=any(level.maintenance_lock for level in levels),
        mode=max(
            (level.mode for level in levels),
            key=lambda mode: MODE_TABLE[mode].restrictiveness,
        ),
        dry_run=controls.dry_run,
    )
