"""The fire bypass: a named construct of the gate.

A wish of class fire skips exactly the gate rules listed in ``FIRE_BYPASS``.
It never skips the maintenance lock and never dry-run (decided), and it never
skips the two rules that describe what is physically possible or already true
("no member can execute the command", "target reached").

The bypass lives in this one place. No gate rule contains an exception for
fire, and a rule that is part of the bypass cannot even be registered for the
class fire (see ``GateRuleRegistration``). Fire is also exempt from every
constraint; the arbiter applies none to a wish of class fire, and a constraint
cannot be registered for that class.
"""

from typing import Final

from custom_components.roller_shutter_suite.core.model import GateRule, WishClass

FIRE_BYPASS: Final[frozenset[GateRule]] = frozenset(
    {
        GateRule.OPERATING_MODE,
        GateRule.PAUSE,
        GateRule.PERSON_AT_WINDOW_DAM,
        GateRule.MANUAL_OVERRIDE_DAM,
        GateRule.MOVEMENT_IN_FLIGHT,
        GateRule.MOTOR_PROTECTION,
        GateRule.COMMAND_BACKOFF,
        GateRule.STAGGERING,
    }
)
"""The gate rules a wish of class fire skips."""

NEVER_SKIPPED: Final[frozenset[GateRule]] = frozenset(GateRule) - FIRE_BYPASS
"""Maintenance lock, no member can execute, target reached, dry-run."""


def skips(wish_class: WishClass, rule: GateRule) -> bool:
    """Return whether a wish of this class skips the gate rule."""
    return wish_class is WishClass.FIRE and rule in FIRE_BYPASS
