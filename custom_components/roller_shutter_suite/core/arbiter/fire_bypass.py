"""The fire bypass: a named construct of the gate.

The bypass names what can never hold back a wish of class fire, as the reason
codes of the gate rules. Fire skips every registered gate rule, or part of a
rule, that can give only these reasons:

- operating mode, pause, both dams, motor protection, command backoff and
  staggering as whole rules;
- of the rule "movement in flight" only the deferral (``movement_in_flight``):
  fire retargets at once.

It never skips the maintenance lock and never dry-run (decided), never the two
rules that describe what is physically possible or already true ("no member
can execute the command", "target reached"), and never the other part of
"movement in flight": a command with the same target whose expectation window
is still running is not sent again, for fire either (``duplicate_command``,
``movement_taken_over``).

The bypass lives in this one place. No gate rule contains an exception for
fire, and a rule that is part of the bypass cannot even be registered for the
class fire (see ``GateRuleRegistration``). Fire is also exempt from every
constraint; the arbiter applies none to a wish of class fire, and a constraint
cannot be registered for that class.
"""

from typing import Final

from custom_components.roller_shutter_suite.core.model import (
    GATE_RULE_REASONS,
    GateRule,
    WishClass,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode

FIRE_BYPASS: Final[frozenset[ReasonCode]] = frozenset(
    {
        ReasonCode.MODE_OFF,
        ReasonCode.MODE_PROTECTION_ONLY,
        ReasonCode.PAUSED,
        ReasonCode.PERSON_AT_WINDOW,
        ReasonCode.MANUAL_OVERRIDE,
        ReasonCode.MOVEMENT_IN_FLIGHT,
        ReasonCode.MIN_CHANGE,
        ReasonCode.MIN_INTERVAL,
        ReasonCode.TRIGGER_TIME_MISSING,
        ReasonCode.COMMAND_BACKOFF,
        ReasonCode.STAGGERED,
    }
)
"""The reasons for which a wish of class fire is never held back."""

NEVER_BYPASSED: Final[frozenset[ReasonCode]] = (
    frozenset().union(*GATE_RULE_REASONS.values()) - FIRE_BYPASS
)
"""Every other reason a gate rule can give; these hold back fire too."""


def bypassed_rules() -> frozenset[GateRule]:
    """Return the gate rules the bypass touches, as a whole or in part."""
    return frozenset(
        rule for rule, reasons in GATE_RULE_REASONS.items() if reasons & FIRE_BYPASS
    )


def skips(wish_class: WishClass, reasons: frozenset[ReasonCode]) -> bool:
    """Return whether a wish of this class skips a rule that gives these reasons."""
    return wish_class is WishClass.FIRE and reasons <= FIRE_BYPASS
